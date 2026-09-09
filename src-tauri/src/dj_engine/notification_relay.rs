//! Bounded FIFO delivery to the UI thread. Never call a scheduler, emitter, or
//! failure callback while holding the mailbox lock.

use std::collections::VecDeque;
use std::sync::{mpsc, Arc, Mutex};
use std::thread;

use super::{lock, STATUS_CHANNEL};

pub(super) const MAX_NOTIFICATIONS: usize = 256;
pub(super) const MAX_NOTIFICATION_BYTES: usize = 4 * 1024 * 1024;
pub(super) const DRAIN_BATCH: usize = 32;

type Task = Box<dyn FnOnce() + Send>;
type Schedule = dyn Fn(Task) -> Result<(), String> + Send + Sync;
type Deliver = dyn Fn(&str, String) -> Result<(), String> + Send + Sync;

struct Notification {
    channel: &'static str,
    payload: String,
}

#[derive(Default)]
struct Mailbox {
    queue: VecDeque<Notification>,
    bytes: usize,
    scheduled: bool,
    closed: bool,
    error: Option<String>,
}

pub(super) struct NotificationRelay {
    mailbox: Mutex<Mailbox>,
    wake: mpsc::SyncSender<()>,
    deliver: Arc<Deliver>,
    on_failure: Arc<dyn Fn(&str) + Send + Sync>,
}

impl NotificationRelay {
    pub(super) fn new(
        schedule: Arc<Schedule>,
        deliver: Arc<Deliver>,
        on_failure: Arc<dyn Fn(&str) + Send + Sync>,
    ) -> Arc<Self> {
        let (wake, receiver) = mpsc::sync_channel(1);
        let relay = Arc::new(Self {
            mailbox: Mutex::new(Mailbox::default()),
            wake,
            deliver,
            on_failure,
        });
        let weak = Arc::downgrade(&relay);
        // Tauri runs run_on_main_thread inline when called from the UI thread.
        // This single worker schedules each *batch* from off-thread so a busy
        // producer cannot recursively drain forever and starve native IPC.
        // Only the drain completion can request the next batch; at most one
        // drain closure is outstanding. The worker never emits or awaits UI.
        thread::spawn(move || {
            while receiver.recv().is_ok() {
                let Some(relay) = weak.upgrade() else { break };
                if lock(&relay.mailbox).closed {
                    break;
                }
                let task_relay = Arc::downgrade(&relay);
                if let Err(error) = schedule(Box::new(move || {
                    if let Some(relay) = task_relay.upgrade() {
                        relay.drain();
                    }
                })) {
                    relay.fail(format!("UI 通知を予約できません: {error}"), false);
                    relay.close();
                    break;
                }
                // Do not retain a sender while waiting: dropping all producers
                // must also release this worker without a shutdown join.
            }
        });
        relay
    }

    pub(super) fn enqueue(&self, channel: &'static str, payload: String) {
        let mut mailbox = lock(&self.mailbox);
        if mailbox.closed || mailbox.error.is_some() {
            return;
        }
        if mailbox.queue.len() >= MAX_NOTIFICATIONS
            || payload.len() > MAX_NOTIFICATION_BYTES.saturating_sub(mailbox.bytes)
        {
            drop(mailbox);
            self.fail(
                format!(
                    "UI 通知キューが上限（{MAX_NOTIFICATIONS} 件 / {MAX_NOTIFICATION_BYTES} bytes）を超えました。エンジンを再起動してください"
                ),
                true,
            );
            return;
        }
        mailbox.bytes += payload.len();
        mailbox.queue.push_back(Notification { channel, payload });
        let wake = !mailbox.scheduled;
        mailbox.scheduled = true;
        drop(mailbox);
        if wake {
            self.wake();
        }
    }

    fn wake(&self) {
        if let Err(mpsc::TrySendError::Disconnected(_)) = self.wake.try_send(()) {
            self.fail("UI 通知スケジューラが終了しました".into(), false);
        }
    }

    fn fail(&self, error: String, notify: bool) {
        let mut mailbox = lock(&self.mailbox);
        if mailbox.closed || mailbox.error.is_some() {
            return;
        }
        mailbox.error = Some(error.clone());
        mailbox.queue.clear();
        mailbox.bytes = 0;
        // A reserved terminal status replaces the now-invalid stream. This is
        // an explicit failure, never a silent sequence gap or coalesced event.
        if notify {
            let payload = serde_json::json!({
                "running": false,
                "reason": "engine_event_delivery_failed",
                "error": error,
            })
            .to_string();
            mailbox.bytes = payload.len();
            mailbox.queue.push_back(Notification {
                channel: STATUS_CHANNEL,
                payload,
            });
        }
        let wake = notify && !mailbox.scheduled;
        mailbox.scheduled |= notify;
        drop(mailbox);
        eprintln!("[dj-engine] {error}");
        (self.on_failure)(&error);
        if wake {
            self.wake();
        }
    }

    fn drain(&self) {
        for _ in 0..DRAIN_BATCH {
            let notification = {
                let mut mailbox = lock(&self.mailbox);
                if mailbox.closed {
                    return;
                }
                let Some(notification) = mailbox.queue.pop_front() else {
                    mailbox.scheduled = false;
                    return;
                };
                mailbox.bytes -= notification.payload.len();
                notification
            };
            // One in-progress payload (also <=4 MiB) is outside the mailbox.
            if let Err(error) = (self.deliver)(notification.channel, notification.payload) {
                self.fail(format!("UI 通知を送出できません: {error}"), true);
            }
        }
        let mut mailbox = lock(&self.mailbox);
        let wake = !mailbox.closed && !mailbox.queue.is_empty();
        mailbox.scheduled = wake;
        drop(mailbox);
        if wake {
            self.wake();
        }
    }

    pub(super) fn error(&self) -> Option<String> {
        lock(&self.mailbox).error.clone()
    }

    pub(super) fn refresh_failure_status(&self) {
        let mut mailbox = lock(&self.mailbox);
        if mailbox.closed || mailbox.error.is_none() {
            return;
        }
        // The shutdown watchdog may discover a forced stop after the first
        // terminal status was consumed. Reserve/coalesce just this terminal
        // status so the frontend re-queries the now-complete error detail.
        let payload = serde_json::json!({
            "running": false,
            "reason": "engine_event_delivery_failed",
        })
        .to_string();
        mailbox.queue.clear();
        mailbox.bytes = payload.len();
        mailbox.queue.push_back(Notification {
            channel: STATUS_CHANNEL,
            payload,
        });
        let wake = !mailbox.scheduled;
        mailbox.scheduled = true;
        drop(mailbox);
        if wake {
            self.wake();
        }
    }

    pub(super) fn close(&self) {
        let mut mailbox = lock(&self.mailbox);
        mailbox.closed = true;
        mailbox.queue.clear();
        mailbox.bytes = 0;
        drop(mailbox);
        // Wakes an idle worker, but never waits for a queued UI callback.
        let _ = self.wake.try_send(());
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::Weak;
    use std::time::Duration;

    const WAIT: Duration = Duration::from_secs(2);

    struct Harness {
        relay: Arc<NotificationRelay>,
        tasks: mpsc::Receiver<Task>,
        delivered: Arc<Mutex<Vec<(String, String)>>>,
        failures: Arc<Mutex<Vec<String>>>,
    }

    impl Harness {
        fn new() -> Self {
            let (sender, tasks) = mpsc::channel();
            let delivered = Arc::new(Mutex::new(Vec::new()));
            let failures = Arc::new(Mutex::new(Vec::new()));
            let output = Arc::clone(&delivered);
            let errors = Arc::clone(&failures);
            let relay = NotificationRelay::new(
                Arc::new(move |task| sender.send(task).map_err(|error| error.to_string())),
                Arc::new(move |channel, payload| {
                    lock(&output).push((channel.to_string(), payload));
                    Ok(())
                }),
                Arc::new(move |error| lock(&errors).push(error.to_string())),
            );
            Self {
                relay,
                tasks,
                delivered,
                failures,
            }
        }

        fn drain_once(&self) {
            self.tasks.recv_timeout(WAIT).unwrap()();
        }
    }

    #[test]
    fn fifo_is_preserved_across_bounded_batches_and_only_one_task_is_pending() {
        let harness = Harness::new();
        for seq in 0..(DRAIN_BATCH * 2 + 3) {
            harness.relay.enqueue("event", seq.to_string());
        }
        let first = harness.tasks.recv_timeout(WAIT).unwrap();
        assert!(harness.tasks.try_recv().is_err());
        first();
        assert_eq!(lock(&harness.delivered).len(), DRAIN_BATCH);
        harness.drain_once();
        assert_eq!(lock(&harness.delivered).len(), DRAIN_BATCH * 2);
        harness.drain_once();
        let actual: Vec<String> = lock(&harness.delivered)
            .iter()
            .map(|(_, value)| value.clone())
            .collect();
        let expected: Vec<String> = (0..DRAIN_BATCH * 2 + 3)
            .map(|seq| seq.to_string())
            .collect();
        assert_eq!(actual, expected);
        assert!(!lock(&harness.relay.mailbox).scheduled);
        // The idle -> scheduled transition must also wake a new drain.
        harness.relay.enqueue("event", "later".into());
        harness.drain_once();
        assert_eq!(lock(&harness.delivered).last().unwrap().1, "later");
        harness.relay.close();
    }

    #[test]
    fn delivery_can_reenter_enqueue_and_query_without_a_mailbox_lock() {
        let (sender, tasks) = mpsc::channel::<Task>();
        let current: Arc<Mutex<Option<Weak<NotificationRelay>>>> = Arc::new(Mutex::new(None));
        let current_in_emit = Arc::clone(&current);
        let output = Arc::new(Mutex::new(Vec::new()));
        let emitted = Arc::clone(&output);
        let relay = NotificationRelay::new(
            Arc::new(move |task| sender.send(task).map_err(|error| error.to_string())),
            Arc::new(move |_, payload| {
                let relay = lock(&current_in_emit).as_ref().unwrap().upgrade().unwrap();
                assert!(relay.error().is_none());
                if payload == "first" {
                    relay.enqueue("event", "second".into());
                }
                lock(&emitted).push(payload);
                Ok(())
            }),
            Arc::new(|error| panic!("unexpected failure: {error}")),
        );
        *lock(&current) = Some(Arc::downgrade(&relay));
        relay.enqueue("event", "first".into());
        tasks.recv_timeout(WAIT).unwrap()();
        assert_eq!(*lock(&output), vec!["first", "second"]);
        assert!(!lock(&relay.mailbox).scheduled);
        relay.close();
    }

    #[test]
    fn count_overflow_fails_once_and_replaces_invalid_stream_with_terminal_status() {
        let harness = Harness::new();
        for _ in 0..MAX_NOTIFICATIONS {
            harness.relay.enqueue("event", "{}".into());
        }
        assert!(harness.relay.error().is_none());
        harness.relay.enqueue("event", "overflow".into());
        harness
            .relay
            .enqueue("event", "ignored after explicit failure".into());
        assert_eq!(lock(&harness.failures).len(), 1);
        assert!(harness.relay.error().unwrap().contains("256"));
        assert_eq!(lock(&harness.relay.mailbox).queue.len(), 1);
        harness.drain_once();
        let delivered = lock(&harness.delivered);
        assert_eq!(delivered.len(), 1);
        assert_eq!(delivered[0].0, STATUS_CHANNEL);
        let status: serde_json::Value = serde_json::from_str(&delivered[0].1).unwrap();
        assert_eq!(status["reason"], "engine_event_delivery_failed");
        assert_eq!(status["running"], false);
        harness.relay.close();
    }

    #[test]
    fn byte_limit_and_single_oversized_notification_fail_explicitly() {
        let harness = Harness::new();
        harness
            .relay
            .enqueue("event", "x".repeat(MAX_NOTIFICATION_BYTES));
        assert!(harness.relay.error().is_none());
        harness.relay.enqueue("event", "x".into());
        assert_eq!(lock(&harness.failures).len(), 1);
        harness.drain_once();
        assert_eq!(lock(&harness.delivered).len(), 1);
        harness.relay.close();

        let oversized = Harness::new();
        oversized
            .relay
            .enqueue("event", "x".repeat(MAX_NOTIFICATION_BYTES + 1));
        assert_eq!(lock(&oversized.failures).len(), 1);
        oversized.drain_once();
        assert_eq!(lock(&oversized.delivered)[0].0, STATUS_CHANNEL);
        oversized.relay.close();
    }

    #[test]
    fn later_shutdown_outcome_resignals_status_through_one_reserved_slot() {
        let harness = Harness::new();
        harness
            .relay
            .enqueue("event", "x".repeat(MAX_NOTIFICATION_BYTES + 1));
        harness.drain_once();
        assert_eq!(lock(&harness.delivered).len(), 1);
        // First status is already consumed before the watchdog completes.
        for _ in 0..MAX_NOTIFICATIONS * 2 {
            harness.relay.refresh_failure_status();
        }
        assert_eq!(lock(&harness.relay.mailbox).queue.len(), 1);
        harness.drain_once();
        assert_eq!(lock(&harness.delivered).len(), 2);
        assert_eq!(lock(&harness.failures).len(), 1);
        harness.relay.close();
        harness.relay.refresh_failure_status();
        assert!(lock(&harness.relay.mailbox).queue.is_empty());
    }

    #[test]
    fn closing_does_not_wait_for_ui_and_invalidates_already_scheduled_delivery() {
        let harness = Harness::new();
        harness.relay.enqueue("event", "before close".into());
        let task = harness.tasks.recv_timeout(WAIT).unwrap();
        harness.relay.close();
        harness.relay.enqueue("event", "after close".into());
        task();
        assert!(lock(&harness.delivered).is_empty());
        assert!(lock(&harness.failures).is_empty());
        // A retained producer cannot keep the closed scheduler worker alive.
        assert!(matches!(
            harness.tasks.recv_timeout(WAIT),
            Err(mpsc::RecvTimeoutError::Disconnected)
        ));
    }

    #[test]
    fn unexecuted_ui_task_does_not_retain_a_closed_relay_or_its_app_handle() {
        let harness = Harness::new();
        harness.relay.enqueue("event", "pending UI task".into());
        let task = harness.tasks.recv_timeout(WAIT).unwrap();
        let weak = Arc::downgrade(&harness.relay);
        harness.relay.close();
        drop(harness.relay);
        // Wait for the scheduling worker (never for the held UI task) to exit.
        assert!(matches!(
            harness.tasks.recv_timeout(WAIT),
            Err(mpsc::RecvTimeoutError::Disconnected)
        ));
        assert!(weak.upgrade().is_none());
        task();
        assert!(lock(&harness.delivered).is_empty());
    }

    #[test]
    fn rejected_schedule_fails_without_waiting_or_retrying() {
        let (failure_sender, failures) = mpsc::channel();
        let relay = NotificationRelay::new(
            Arc::new(|_| Err("event loop closed".into())),
            Arc::new(|_, _| panic!("must not emit when scheduling failed")),
            Arc::new(move |error| {
                failure_sender.send(error.to_string()).unwrap();
            }),
        );
        relay.enqueue("event", "{}".into());
        assert!(failures
            .recv_timeout(WAIT)
            .unwrap()
            .contains("event loop closed"));
        relay.enqueue("event", "{}".into());
        assert!(failures.try_recv().is_err());
        assert!(relay.error().is_some());
    }

    #[test]
    fn failed_delivery_emits_one_terminal_status_without_retrying_the_event() {
        let (sender, tasks) = mpsc::channel::<Task>();
        let output = Arc::new(Mutex::new(Vec::new()));
        let emitted = Arc::clone(&output);
        let failures = Arc::new(Mutex::new(Vec::new()));
        let failed = Arc::clone(&failures);
        let relay = NotificationRelay::new(
            Arc::new(move |task| sender.send(task).map_err(|error| error.to_string())),
            Arc::new(move |channel, _| {
                lock(&emitted).push(channel.to_string());
                Err("webview closed".into())
            }),
            Arc::new(move |error| lock(&failed).push(error.to_string())),
        );
        relay.enqueue("event", "{}".into());
        tasks.recv_timeout(WAIT).unwrap()();
        assert_eq!(*lock(&output), vec!["event", STATUS_CHANNEL]);
        assert_eq!(lock(&failures).len(), 1);
        assert!(!lock(&relay.mailbox).scheduled);
        relay.close();
    }
}
