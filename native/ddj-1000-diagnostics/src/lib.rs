use serde::{Deserialize, Serialize};

#[cfg(target_os = "macos")]
mod macos;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum DeviceFamily {
    #[serde(rename = "ddj_1000")]
    Ddj1000,
    #[serde(rename = "ddj_1000_srt")]
    Ddj1000Srt,
    Other,
}

pub fn classify_name(name: &str) -> DeviceFamily {
    let normalized: String = name
        .chars()
        .filter(|c| c.is_ascii_alphanumeric())
        .flat_map(char::to_uppercase)
        .collect();
    if normalized.contains("DDJ1000SRT") {
        DeviceFamily::Ddj1000Srt
    } else if normalized.contains("DDJ1000") {
        DeviceFamily::Ddj1000
    } else {
        DeviceFamily::Other
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct SampleRateRange {
    pub min_hz: f64,
    pub max_hz: f64,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct AudioDevice {
    pub object_id: u32,
    pub uid: String,
    pub name: String,
    pub family: DeviceFamily,
    pub input_channels: u32,
    pub output_channels: u32,
    pub nominal_sample_rate_hz: f64,
    pub available_sample_rates: Vec<SampleRateRange>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum MidiDirection {
    Source,
    Destination,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct MidiEndpoint {
    pub endpoint_ref: u32,
    pub unique_id: i32,
    pub name: String,
    pub family: DeviceFamily,
    pub direction: MidiDirection,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ScanReport {
    pub schema_version: u32,
    pub platform: String,
    pub audio_devices: Vec<AudioDevice>,
    pub midi_sources: Vec<MidiEndpoint>,
    pub midi_destinations: Vec<MidiEndpoint>,
    /** Per-device read failures; one broken endpoint must not hide a valid DDJ. */
    #[serde(default)]
    pub warnings: Vec<String>,
}

impl ScanReport {
    pub fn ddj_1000_observed(&self) -> bool {
        self.audio_devices
            .iter()
            .any(|d| d.family == DeviceFamily::Ddj1000)
            || self
                .midi_sources
                .iter()
                .chain(&self.midi_destinations)
                .any(|d| d.family == DeviceFamily::Ddj1000)
    }

    pub fn ddj_1000_srt_observed(&self) -> bool {
        self.audio_devices
            .iter()
            .any(|d| d.family == DeviceFamily::Ddj1000Srt)
            || self
                .midi_sources
                .iter()
                .chain(&self.midi_destinations)
                .any(|d| d.family == DeviceFamily::Ddj1000Srt)
    }
}

pub fn scan() -> Result<ScanReport, String> {
    #[cfg(target_os = "macos")]
    {
        macos::scan()
    }
    #[cfg(not(target_os = "macos"))]
    {
        Err("DDJ discovery requires macOS CoreAudio and CoreMIDI".into())
    }
}

pub fn monitor_source(unique_id: i32, seconds: u64, json: bool) -> Result<(), String> {
    #[cfg(target_os = "macos")]
    {
        macos::monitor_source(unique_id, seconds, json)
    }
    #[cfg(not(target_os = "macos"))]
    {
        let _ = (unique_id, seconds, json);
        Err("MIDI monitoring requires macOS CoreMIDI".into())
    }
}

pub fn human_report(report: &ScanReport) -> String {
    let mut out = format!(
        "DDJ-1000 diagnostics (read-only)\nPlatform: {}\n\nAudio devices:\n",
        report.platform
    );
    if report.audio_devices.is_empty() {
        out.push_str("  (none)\n");
    }
    for d in &report.audio_devices {
        let rates = d
            .available_sample_rates
            .iter()
            .map(|r| {
                if r.min_hz == r.max_hz {
                    format!("{}", r.min_hz)
                } else {
                    format!("{}-{}", r.min_hz, r.max_hz)
                }
            })
            .collect::<Vec<_>>()
            .join(", ");
        out.push_str(&format!(
            "  [{}] {}\n    object-id={} uid={} input={} output={} nominal={}Hz available=[{}]\n",
            family_label(d.family),
            d.name,
            d.object_id,
            d.uid,
            d.input_channels,
            d.output_channels,
            d.nominal_sample_rate_hz,
            rates
        ));
    }
    append_midi(
        &mut out,
        "MIDI sources (receive from controller)",
        &report.midi_sources,
    );
    if !report.warnings.is_empty() {
        out.push_str("\nWarnings (other devices were still scanned):\n");
        for warning in &report.warnings {
            out.push_str(&format!("  - {warning}\n"));
        }
    }
    append_midi(
        &mut out,
        "MIDI destinations (listed only; this tool never transmits)",
        &report.midi_destinations,
    );
    out.push_str("\nObserved-name validation:\n");
    out.push_str(&format!(
        "  DDJ-1000 (non-SRT): {}\n  DDJ-1000SRT: {}\n",
        yes_no(report.ddj_1000_observed()),
        yes_no(report.ddj_1000_srt_observed())
    ));
    out
}

fn append_midi(out: &mut String, heading: &str, endpoints: &[MidiEndpoint]) {
    out.push_str(&format!("\n{heading}:\n"));
    if endpoints.is_empty() {
        out.push_str("  (none)\n");
    }
    for e in endpoints {
        out.push_str(&format!(
            "  [{}] {} (unique-id={}, endpoint-ref={})\n",
            family_label(e.family),
            e.name,
            e.unique_id,
            e.endpoint_ref
        ));
    }
}

fn family_label(family: DeviceFamily) -> &'static str {
    match family {
        DeviceFamily::Ddj1000 => "DDJ-1000",
        DeviceFamily::Ddj1000Srt => "DDJ-1000SRT (different hardware)",
        DeviceFamily::Other => "other",
    }
}

fn yes_no(value: bool) -> &'static str {
    if value {
        "yes"
    } else {
        "no"
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn classifies_non_srt_without_confusing_srt() {
        assert_eq!(classify_name("Pioneer DJ DDJ-1000"), DeviceFamily::Ddj1000);
        assert_eq!(classify_name("DDJ_1000 MIDI"), DeviceFamily::Ddj1000);
        assert_eq!(classify_name("DDJ-1000SRT"), DeviceFamily::Ddj1000Srt);
        assert_eq!(classify_name("Built-in Output"), DeviceFamily::Other);
    }

    #[test]
    fn fixture_round_trip_and_validation_are_stable() {
        let fixture = include_str!("../tests/fixtures/mixed-scan.json");
        let report: ScanReport = serde_json::from_str(fixture).unwrap();
        assert!(report.ddj_1000_observed());
        assert!(report.ddj_1000_srt_observed());
        let human = human_report(&report);
        assert!(human.contains("DDJ-1000 (non-SRT): yes"));
        assert!(human.contains("DDJ-1000SRT: yes"));
        assert!(human.contains("this tool never transmits"));
    }
}
