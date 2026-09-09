//! Minimal, read-only bindings to the macOS Accessibility API.
//!
//! Only copy/read entry points are declared here. There is deliberately no
//! binding for `AXUIElementSetAttributeValue` or `AXUIElementPerformAction`, so
//! this module cannot drive rekordbox even by mistake.

use core_foundation::array::{CFArray, CFArrayRef};
use std::cell::Cell;
use std::time::{Duration, Instant};
thread_local! { static DEADLINE: Cell<Option<Instant>> = const { Cell::new(None) }; }
pub fn begin_read() {
    DEADLINE.with(|d| d.set(Some(Instant::now() + Duration::from_millis(1200))));
}
pub fn budget_expired() -> bool {
    DEADLINE.with(|d| d.get().is_some_and(|end| Instant::now() >= end))
}
use core_foundation::base::{CFGetTypeID, CFRelease, CFRetain, CFTypeID, CFTypeRef, TCFType};
use core_foundation::boolean::CFBoolean;
use core_foundation::dictionary::CFDictionary;
use core_foundation::string::{CFString, CFStringRef};
use std::ffi::c_void;

pub type AXUIElementRef = CFTypeRef;

#[link(name = "ApplicationServices", kind = "framework")]
extern "C" {
    fn AXIsProcessTrusted() -> u8;
    fn AXIsProcessTrustedWithOptions(options: *const c_void) -> u8;
    fn AXUIElementCreateApplication(pid: i32) -> AXUIElementRef;
    fn AXUIElementCopyAttributeValue(
        element: AXUIElementRef,
        attribute: CFStringRef,
        value: *mut CFTypeRef,
    ) -> i32;
    fn AXUIElementSetMessagingTimeout(element: AXUIElementRef, timeout: f32) -> i32;
    fn AXUIElementGetTypeID() -> CFTypeID;
    fn AXValueGetTypeID() -> CFTypeID;
    fn AXValueGetValue(value: CFTypeRef, the_type: u32, value_ptr: *mut c_void) -> u8;
}

extern "C" {
    fn CFArrayGetCount(array: CFArrayRef) -> isize;
    fn CFArrayGetValueAtIndex(array: CFArrayRef, index: isize) -> *const c_void;
    fn proc_listallpids(buffer: *mut c_void, buffersize: i32) -> i32;
    fn proc_pidpath(pid: i32, buffer: *mut c_void, buffersize: u32) -> i32;
}

const K_AX_VALUE_CG_POINT: u32 = 1;
const K_AX_VALUE_CG_SIZE: u32 = 2;

#[repr(C)]
#[derive(Default, Clone, Copy)]
struct CGPoint {
    x: f64,
    y: f64,
}

#[repr(C)]
#[derive(Default, Clone, Copy)]
struct CGSize {
    width: f64,
    height: f64,
}

/// An owned, retained accessibility element.
///
/// `AXUIElementRef` is a CoreFoundation object, so ownership is refcount based.
/// Wrapping it keeps every copy path balanced and lets cached references live in
/// the plugin state across polls without re-walking from the application root.
pub struct AxRef(CFTypeRef);

// Accessibility elements are CF objects and may be messaged from any thread; the
// containing state is behind a mutex, so only one thread touches one at a time.
unsafe impl Send for AxRef {}

impl AxRef {
    /// Takes ownership of a reference we already own (create/copy result).
    unsafe fn from_owned(raw: CFTypeRef) -> Option<Self> {
        if raw.is_null() {
            None
        } else {
            Some(Self(raw))
        }
    }

    /// Retains a reference we only borrowed (e.g. an element inside a CFArray).
    unsafe fn from_borrowed(raw: CFTypeRef) -> Option<Self> {
        if raw.is_null() {
            None
        } else {
            Some(Self(CFRetain(raw)))
        }
    }

    pub fn as_raw(&self) -> CFTypeRef {
        self.0
    }
}

impl Drop for AxRef {
    fn drop(&mut self) {
        unsafe { CFRelease(self.0) }
    }
}

pub fn is_process_trusted() -> bool {
    unsafe { AXIsProcessTrusted() != 0 }
}

/// Shows the system's "grant accessibility access" prompt. User initiated only.
pub fn prompt_for_trust() -> bool {
    let key = CFString::new("AXTrustedCheckOptionPrompt");
    let options = CFDictionary::from_CFType_pairs(&[(key, CFBoolean::true_value())]);
    unsafe { AXIsProcessTrustedWithOptions(options.as_CFTypeRef() as *const c_void) != 0 }
}

/// The pid of the main rekordbox executable, plus its path.
///
/// rekordbox also runs agent and renderer helper processes out of the same
/// bundle; only the top-level executable owns the deck window, so match on the
/// full executable path rather than on a process name.
pub fn find_rekordbox_process() -> Option<(i32, String)> {
    let mut pids = vec![0i32; 16384];
    let pid_count = unsafe {
        proc_listallpids(
            pids.as_mut_ptr() as *mut c_void,
            (pids.len() * std::mem::size_of::<i32>()) as i32,
        )
    };
    if pid_count <= 0 {
        return None;
    }
    let count = (pid_count as usize).min(pids.len());
    for &pid in &pids[..count] {
        if pid <= 0 {
            continue;
        }
        if let Some(path) = executable_path(pid) {
            if is_rekordbox_executable(&path) {
                return Some((pid, path));
            }
        }
    }
    None
}

pub fn executable_path(pid: i32) -> Option<String> {
    let mut buffer = vec![0u8; 4096];
    let written =
        unsafe { proc_pidpath(pid, buffer.as_mut_ptr() as *mut c_void, buffer.len() as u32) };
    if written <= 0 {
        return None;
    }
    Some(String::from_utf8_lossy(&buffer[..written as usize]).into_owned())
}

/// True for `<anywhere>/rekordbox.app/Contents/MacOS/rekordbox`.
///
/// Helper processes live deeper inside the bundle under their own `.app`, so an
/// exact suffix match excludes them without hardcoding an install location.
pub fn is_rekordbox_executable(path: &str) -> bool {
    path.ends_with("/rekordbox.app/Contents/MacOS/rekordbox")
}

pub fn application_element(pid: i32) -> Option<AxRef> {
    unsafe { AxRef::from_owned(AXUIElementCreateApplication(pid)) }
}

fn copy_attribute(element: CFTypeRef, name: &str) -> Option<CFTypeRef> {
    if budget_expired() {
        return None;
    }
    // Set the timeout on every element; child elements do not inherit it.
    let remaining = DEADLINE.with(|d| {
        d.get()
            .map(|end| end.saturating_duration_since(Instant::now()).as_secs_f32())
            .unwrap_or(0.15)
    });
    if remaining <= 0.0 {
        return None;
    }
    if unsafe { AXUIElementSetMessagingTimeout(element, remaining.min(0.15)) } != 0 {
        return None;
    }
    let key = CFString::new(name);
    let mut out: CFTypeRef = std::ptr::null();
    let status =
        unsafe { AXUIElementCopyAttributeValue(element, key.as_concrete_TypeRef(), &mut out) };
    if status != 0 || out.is_null() {
        None
    } else {
        Some(out)
    }
}

pub fn attribute_string(element: CFTypeRef, name: &str) -> Option<String> {
    let raw = copy_attribute(element, name)?;
    unsafe {
        let value = if CFGetTypeID(raw) == CFString::type_id() {
            Some(CFString::wrap_under_get_rule(raw as CFStringRef).to_string())
        } else {
            None
        };
        CFRelease(raw);
        value
    }
}

fn attribute_ax_value<T: Copy + Default>(
    element: CFTypeRef,
    name: &str,
    value_type: u32,
) -> Option<T> {
    let raw = copy_attribute(element, name)?;
    unsafe {
        let mut slot = T::default();
        let ok = CFGetTypeID(raw) == AXValueGetTypeID()
            && AXValueGetValue(raw, value_type, &mut slot as *mut T as *mut c_void) != 0;
        CFRelease(raw);
        if ok {
            Some(slot)
        } else {
            None
        }
    }
}

pub fn attribute_position(element: CFTypeRef, name: &str) -> Option<(f64, f64)> {
    attribute_ax_value::<CGPoint>(element, name, K_AX_VALUE_CG_POINT).map(|p| (p.x, p.y))
}

pub fn attribute_size(element: CFTypeRef, name: &str) -> Option<(f64, f64)> {
    attribute_ax_value::<CGSize>(element, name, K_AX_VALUE_CG_SIZE).map(|s| (s.width, s.height))
}

/// Reads an attribute that holds an array of accessibility elements.
///
/// Used for `AXChildren` and `AXWindows`. `AXWindows` is what keeps the ~800
/// node menu bar out of the walk: we never start from the application element's
/// children, only from a window.
pub fn attribute_elements(element: CFTypeRef, name: &str, max: usize) -> Vec<AxRef> {
    let Some(raw) = copy_attribute(element, name) else {
        return Vec::new();
    };
    let mut elements = Vec::new();
    unsafe {
        if CFGetTypeID(raw) != CFArray::<CFTypeRef>::type_id() {
            CFRelease(raw);
            return elements;
        }
        let array = raw as CFArrayRef;
        let count = CFArrayGetCount(array).max(0) as usize;
        for index in 0..count.min(max) {
            let child = CFArrayGetValueAtIndex(array, index as isize) as CFTypeRef;
            if child.is_null() || CFGetTypeID(child) != AXUIElementGetTypeID() {
                continue;
            }
            if let Some(owned) = AxRef::from_borrowed(child) {
                elements.push(owned);
            }
        }
        CFRelease(raw);
    }
    elements
}
