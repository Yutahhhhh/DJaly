use crate::{classify_name, AudioDevice, MidiDirection, MidiEndpoint, SampleRateRange, ScanReport};
use serde_json::json;
use std::ffi::{c_char, c_void, CStr};
use std::mem::{size_of, MaybeUninit};
use std::ptr;
use std::slice;
use std::thread;
use std::time::Duration;

type OSStatus = i32;
type AudioObjectID = u32;
type MIDIObjectRef = u32;
type MIDIEndpointRef = u32;
type MIDIClientRef = u32;
type MIDIPortRef = u32;
type CFStringRef = *const c_void;

const fn fourcc(bytes: &[u8; 4]) -> u32 {
    u32::from_be_bytes(*bytes)
}

const SYSTEM_AUDIO_OBJECT: AudioObjectID = 1;
const PROPERTY_DEVICES: u32 = fourcc(b"dev#");
const PROPERTY_NAME: u32 = fourcc(b"lnam");
const PROPERTY_DEVICE_UID: u32 = fourcc(b"uid ");
const PROPERTY_NOMINAL_RATE: u32 = fourcc(b"nsrt");
const PROPERTY_AVAILABLE_RATES: u32 = fourcc(b"nsr#");
const PROPERTY_STREAM_CONFIGURATION: u32 = fourcc(b"slay");
const SCOPE_GLOBAL: u32 = fourcc(b"glob");
const SCOPE_INPUT: u32 = fourcc(b"inpt");
const SCOPE_OUTPUT: u32 = fourcc(b"outp");
const ELEMENT_MAIN: u32 = 0;
const UTF8_ENCODING: u32 = 0x0800_0100;

#[repr(C)]
#[derive(Clone, Copy)]
struct AudioObjectPropertyAddress {
    selector: u32,
    scope: u32,
    element: u32,
}

#[repr(C)]
#[derive(Clone, Copy)]
struct AudioValueRange {
    minimum: f64,
    maximum: f64,
}

#[repr(C)]
struct AudioBuffer {
    number_channels: u32,
    data_byte_size: u32,
    data: *mut c_void,
}

#[repr(C)]
struct AudioBufferList {
    number_buffers: u32,
    buffers: [AudioBuffer; 1],
}

#[repr(C, packed(4))]
struct MIDIPacket {
    timestamp: u64,
    length: u16,
    data: [u8; 256],
}

#[repr(C, packed(4))]
struct MIDIPacketList {
    number_packets: u32,
    packet: [MIDIPacket; 1],
}

#[link(name = "CoreAudio", kind = "framework")]
extern "C" {
    fn AudioObjectGetPropertyDataSize(
        object_id: AudioObjectID,
        address: *const AudioObjectPropertyAddress,
        qualifier_data_size: u32,
        qualifier_data: *const c_void,
        data_size: *mut u32,
    ) -> OSStatus;
    fn AudioObjectGetPropertyData(
        object_id: AudioObjectID,
        address: *const AudioObjectPropertyAddress,
        qualifier_data_size: u32,
        qualifier_data: *const c_void,
        data_size: *mut u32,
        data: *mut c_void,
    ) -> OSStatus;
}

type MIDIReadProc = Option<unsafe extern "C" fn(*const MIDIPacketList, *mut c_void, *mut c_void)>;

#[link(name = "CoreMIDI", kind = "framework")]
extern "C" {
    static kMIDIPropertyDisplayName: CFStringRef;
    static kMIDIPropertyName: CFStringRef;
    static kMIDIPropertyUniqueID: CFStringRef;

    fn MIDIGetNumberOfSources() -> usize;
    fn MIDIGetSource(index: usize) -> MIDIEndpointRef;
    fn MIDIGetNumberOfDestinations() -> usize;
    fn MIDIGetDestination(index: usize) -> MIDIEndpointRef;
    fn MIDIObjectGetStringProperty(
        object: MIDIObjectRef,
        property_id: CFStringRef,
        value: *mut CFStringRef,
    ) -> OSStatus;
    fn MIDIObjectGetIntegerProperty(
        object: MIDIObjectRef,
        property_id: CFStringRef,
        value: *mut i32,
    ) -> OSStatus;
    fn MIDIClientCreate(
        name: CFStringRef,
        notify_proc: *const c_void,
        notify_ref_con: *mut c_void,
        out_client: *mut MIDIClientRef,
    ) -> OSStatus;
    fn MIDIInputPortCreate(
        client: MIDIClientRef,
        port_name: CFStringRef,
        read_proc: MIDIReadProc,
        ref_con: *mut c_void,
        out_port: *mut MIDIPortRef,
    ) -> OSStatus;
    fn MIDIPortConnectSource(
        port: MIDIPortRef,
        source: MIDIEndpointRef,
        conn_ref_con: *mut c_void,
    ) -> OSStatus;
    fn MIDIPortDisconnectSource(port: MIDIPortRef, source: MIDIEndpointRef) -> OSStatus;
    fn MIDIPortDispose(port: MIDIPortRef) -> OSStatus;
    fn MIDIClientDispose(client: MIDIClientRef) -> OSStatus;
}

#[link(name = "CoreFoundation", kind = "framework")]
extern "C" {
    fn CFStringCreateWithCString(
        allocator: *const c_void,
        c_str: *const c_char,
        encoding: u32,
    ) -> CFStringRef;
    fn CFStringGetCStringPtr(string: CFStringRef, encoding: u32) -> *const c_char;
    fn CFStringGetCString(
        string: CFStringRef,
        buffer: *mut c_char,
        buffer_size: isize,
        encoding: u32,
    ) -> bool;
    fn CFStringGetMaximumSizeForEncoding(length: isize, encoding: u32) -> isize;
    fn CFStringGetLength(string: CFStringRef) -> isize;
    fn CFRelease(value: *const c_void);
}

fn address(selector: u32, scope: u32) -> AudioObjectPropertyAddress {
    AudioObjectPropertyAddress {
        selector,
        scope,
        element: ELEMENT_MAIN,
    }
}

fn status(operation: &str, value: OSStatus) -> Result<(), String> {
    if value == 0 {
        Ok(())
    } else {
        let code = value.to_be_bytes();
        let printable = code.iter().all(|b| b.is_ascii_graphic() || *b == b' ');
        if printable {
            Err(format!(
                "{operation} failed: OSStatus {value} ('{}')",
                String::from_utf8_lossy(&code)
            ))
        } else {
            Err(format!("{operation} failed: OSStatus {value}"))
        }
    }
}

unsafe fn cf_string_to_string(value: CFStringRef) -> Result<String, String> {
    if value.is_null() {
        return Err("CoreFoundation returned a null string".into());
    }
    let direct = CFStringGetCStringPtr(value, UTF8_ENCODING);
    if !direct.is_null() {
        return Ok(CStr::from_ptr(direct).to_string_lossy().into_owned());
    }
    let length = CFStringGetLength(value);
    let capacity = CFStringGetMaximumSizeForEncoding(length, UTF8_ENCODING) + 1;
    let mut buffer = vec![0_i8; capacity as usize];
    if !CFStringGetCString(value, buffer.as_mut_ptr(), capacity, UTF8_ENCODING) {
        return Err("could not convert CoreFoundation string to UTF-8".into());
    }
    Ok(CStr::from_ptr(buffer.as_ptr())
        .to_string_lossy()
        .into_owned())
}

unsafe fn audio_cf_string(object: AudioObjectID, selector: u32) -> Result<String, String> {
    let addr = address(selector, SCOPE_GLOBAL);
    let mut value: CFStringRef = ptr::null();
    let mut size = size_of::<CFStringRef>() as u32;
    status(
        "AudioObjectGetPropertyData(string)",
        AudioObjectGetPropertyData(
            object,
            &addr,
            0,
            ptr::null(),
            &mut size,
            &mut value as *mut _ as *mut c_void,
        ),
    )?;
    let result = cf_string_to_string(value);
    if !value.is_null() {
        CFRelease(value);
    }
    result
}

unsafe fn audio_scalar<T: Copy>(
    object: AudioObjectID,
    selector: u32,
    scope: u32,
) -> Result<T, String> {
    let addr = address(selector, scope);
    let mut value = MaybeUninit::<T>::uninit();
    let mut size = size_of::<T>() as u32;
    status(
        "AudioObjectGetPropertyData(scalar)",
        AudioObjectGetPropertyData(
            object,
            &addr,
            0,
            ptr::null(),
            &mut size,
            value.as_mut_ptr() as *mut c_void,
        ),
    )?;
    if size as usize != size_of::<T>() {
        return Err(format!("CoreAudio returned unexpected scalar size {size}"));
    }
    Ok(value.assume_init())
}

unsafe fn audio_ids() -> Result<Vec<AudioObjectID>, String> {
    let addr = address(PROPERTY_DEVICES, SCOPE_GLOBAL);
    let mut size = 0_u32;
    status(
        "AudioObjectGetPropertyDataSize(devices)",
        AudioObjectGetPropertyDataSize(SYSTEM_AUDIO_OBJECT, &addr, 0, ptr::null(), &mut size),
    )?;
    if !(size as usize).is_multiple_of(size_of::<AudioObjectID>()) {
        return Err("CoreAudio returned a malformed device list".into());
    }
    let mut devices = vec![0; size as usize / size_of::<AudioObjectID>()];
    status(
        "AudioObjectGetPropertyData(devices)",
        AudioObjectGetPropertyData(
            SYSTEM_AUDIO_OBJECT,
            &addr,
            0,
            ptr::null(),
            &mut size,
            devices.as_mut_ptr() as *mut c_void,
        ),
    )?;
    Ok(devices)
}

unsafe fn channel_count(device: AudioObjectID, scope: u32) -> Result<u32, String> {
    let addr = address(PROPERTY_STREAM_CONFIGURATION, scope);
    let mut size = 0_u32;
    status(
        "AudioObjectGetPropertyDataSize(stream configuration)",
        AudioObjectGetPropertyDataSize(device, &addr, 0, ptr::null(), &mut size),
    )?;
    // u64 storage provides sufficient alignment for AudioBufferList/AudioBuffer.
    let mut storage = vec![0_u64; (size as usize).div_ceil(8)];
    status(
        "AudioObjectGetPropertyData(stream configuration)",
        AudioObjectGetPropertyData(
            device,
            &addr,
            0,
            ptr::null(),
            &mut size,
            storage.as_mut_ptr() as *mut c_void,
        ),
    )?;
    let list = &*(storage.as_ptr() as *const AudioBufferList);
    let buffers = slice::from_raw_parts(list.buffers.as_ptr(), list.number_buffers as usize);
    Ok(buffers.iter().map(|b| b.number_channels).sum())
}

unsafe fn available_rates(device: AudioObjectID) -> Result<Vec<SampleRateRange>, String> {
    let addr = address(PROPERTY_AVAILABLE_RATES, SCOPE_GLOBAL);
    let mut size = 0_u32;
    status(
        "AudioObjectGetPropertyDataSize(sample rates)",
        AudioObjectGetPropertyDataSize(device, &addr, 0, ptr::null(), &mut size),
    )?;
    if !(size as usize).is_multiple_of(size_of::<AudioValueRange>()) {
        return Err("CoreAudio returned malformed sample-rate ranges".into());
    }
    let mut ranges = vec![
        AudioValueRange {
            minimum: 0.0,
            maximum: 0.0,
        };
        size as usize / size_of::<AudioValueRange>()
    ];
    status(
        "AudioObjectGetPropertyData(sample rates)",
        AudioObjectGetPropertyData(
            device,
            &addr,
            0,
            ptr::null(),
            &mut size,
            ranges.as_mut_ptr() as *mut c_void,
        ),
    )?;
    Ok(ranges
        .into_iter()
        .map(|r| SampleRateRange {
            min_hz: r.minimum,
            max_hz: r.maximum,
        })
        .collect())
}

unsafe fn midi_string(object: MIDIObjectRef) -> Result<String, String> {
    for property in [kMIDIPropertyDisplayName, kMIDIPropertyName] {
        let mut value: CFStringRef = ptr::null();
        if MIDIObjectGetStringProperty(object, property, &mut value) == 0 && !value.is_null() {
            let converted = cf_string_to_string(value);
            CFRelease(value);
            if converted.is_ok() {
                return converted;
            }
        }
    }
    Err(format!("CoreMIDI endpoint {object} has no readable name"))
}

unsafe fn midi_endpoint(
    endpoint: MIDIEndpointRef,
    direction: MidiDirection,
) -> Result<MidiEndpoint, String> {
    let name = midi_string(endpoint)?;
    let mut unique_id = 0_i32;
    status(
        "MIDIObjectGetIntegerProperty(unique ID)",
        MIDIObjectGetIntegerProperty(endpoint, kMIDIPropertyUniqueID, &mut unique_id),
    )?;
    Ok(MidiEndpoint {
        endpoint_ref: endpoint,
        unique_id,
        family: classify_name(&name),
        name,
        direction,
    })
}

pub fn scan() -> Result<ScanReport, String> {
    unsafe {
        let mut audio_devices = Vec::new();
        let mut warnings = Vec::new();
        for object_id in audio_ids()? {
            let device = (|| -> Result<AudioDevice, String> {
                let name = audio_cf_string(object_id, PROPERTY_NAME)?;
                Ok(AudioDevice {
                    object_id,
                    uid: audio_cf_string(object_id, PROPERTY_DEVICE_UID)?,
                    family: classify_name(&name),
                    name,
                    input_channels: channel_count(object_id, SCOPE_INPUT)?,
                    output_channels: channel_count(object_id, SCOPE_OUTPUT)?,
                    nominal_sample_rate_hz: audio_scalar::<f64>(
                        object_id,
                        PROPERTY_NOMINAL_RATE,
                        SCOPE_GLOBAL,
                    )?,
                    available_sample_rates: available_rates(object_id)?,
                })
            })();
            match device {
                Ok(device) => audio_devices.push(device),
                Err(error) => warnings.push(format!("CoreAudio object {object_id}: {error}")),
            }
        }

        let mut midi_sources = Vec::new();
        for index in 0..MIDIGetNumberOfSources() {
            let endpoint = MIDIGetSource(index);
            if endpoint != 0 {
                match midi_endpoint(endpoint, MidiDirection::Source) {
                    Ok(endpoint) => midi_sources.push(endpoint),
                    Err(error) => warnings.push(format!("CoreMIDI source index {index}: {error}")),
                }
            }
        }
        let mut midi_destinations = Vec::new();
        for index in 0..MIDIGetNumberOfDestinations() {
            let endpoint = MIDIGetDestination(index);
            if endpoint != 0 {
                match midi_endpoint(endpoint, MidiDirection::Destination) {
                    Ok(endpoint) => midi_destinations.push(endpoint),
                    Err(error) => {
                        warnings.push(format!("CoreMIDI destination index {index}: {error}"))
                    }
                }
            }
        }
        Ok(ScanReport {
            schema_version: 1,
            platform: "macos".into(),
            audio_devices,
            midi_sources,
            midi_destinations,
            warnings,
        })
    }
}

struct MonitorContext {
    json: bool,
}

unsafe extern "C" fn midi_read(
    packet_list: *const MIDIPacketList,
    read_proc_ref_con: *mut c_void,
    _src_conn_ref_con: *mut c_void,
) {
    if packet_list.is_null() || read_proc_ref_con.is_null() {
        return;
    }
    let context = &*(read_proc_ref_con as *const MonitorContext);
    let list = &*packet_list;
    let mut packet = list.packet.as_ptr();
    for _ in 0..list.number_packets {
        let p = &*packet;
        let timestamp = p.timestamp;
        let length = usize::from(p.length);
        let bytes = std::slice::from_raw_parts(p.data.as_ptr(), length);
        if context.json {
            println!(
                "{}",
                json!({"timestamp": timestamp, "length": length, "bytes": bytes})
            );
        } else {
            let hex = bytes
                .iter()
                .map(|byte| format!("{byte:02X}"))
                .collect::<Vec<_>>()
                .join(" ");
            println!("timestamp={timestamp} bytes={hex}");
        }
        let next = p.data.as_ptr().add(length) as usize;
        packet = ((next + 3) & !3) as *const MIDIPacket;
    }
}

struct MidiResources {
    client: MIDIClientRef,
    port: MIDIPortRef,
    source: MIDIEndpointRef,
}

impl Drop for MidiResources {
    fn drop(&mut self) {
        unsafe {
            if self.port != 0 && self.source != 0 {
                let _ = MIDIPortDisconnectSource(self.port, self.source);
            }
            if self.port != 0 {
                let _ = MIDIPortDispose(self.port);
            }
            if self.client != 0 {
                let _ = MIDIClientDispose(self.client);
            }
        }
    }
}

unsafe fn make_cf_string(bytes_with_nul: &'static [u8]) -> Result<CFStringRef, String> {
    let value = CFStringCreateWithCString(
        ptr::null(),
        bytes_with_nul.as_ptr() as *const c_char,
        UTF8_ENCODING,
    );
    if value.is_null() {
        Err("CFStringCreateWithCString failed".into())
    } else {
        Ok(value)
    }
}

pub fn monitor_source(unique_id: i32, seconds: u64, json_output: bool) -> Result<(), String> {
    unsafe {
        let matching: Vec<_> = (0..MIDIGetNumberOfSources())
            .filter_map(|index| {
                let endpoint = MIDIGetSource(index);
                if endpoint == 0 {
                    return None;
                }
                let mut observed_id = 0_i32;
                (MIDIObjectGetIntegerProperty(endpoint, kMIDIPropertyUniqueID, &mut observed_id)
                    == 0
                    && observed_id == unique_id)
                    .then_some(endpoint)
            })
            .collect();
        if matching.len() != 1 {
            return Err(format!(
                "--source-id {unique_id} matched {} sources; run scan and select one exact unique ID",
                matching.len()
            ));
        }
        let source = matching[0];
        let source_name = midi_string(source)?;
        let client_name = make_cf_string(b"plumdeck DDJ diagnostics\0")?;
        let port_name = make_cf_string(b"plumdeck monitor input\0")?;
        let mut resources = MidiResources {
            client: 0,
            port: 0,
            source,
        };
        let mut context = Box::new(MonitorContext { json: json_output });
        let result = (|| {
            status(
                "MIDIClientCreate",
                MIDIClientCreate(
                    client_name,
                    ptr::null(),
                    ptr::null_mut(),
                    &mut resources.client,
                ),
            )?;
            status(
                "MIDIInputPortCreate",
                MIDIInputPortCreate(
                    resources.client,
                    port_name,
                    Some(midi_read),
                    &mut *context as *mut MonitorContext as *mut c_void,
                    &mut resources.port,
                ),
            )?;
            status(
                "MIDIPortConnectSource",
                MIDIPortConnectSource(resources.port, source, ptr::null_mut()),
            )?;
            eprintln!(
                "Monitoring receive-only source '{}' (unique-id={}) for {} seconds; no MIDI is transmitted.",
                source_name, unique_id, seconds
            );
            thread::sleep(Duration::from_secs(seconds));
            Ok(())
        })();
        CFRelease(port_name);
        CFRelease(client_name);
        // Disconnect/dispose the callback-bearing port before freeing its context.
        drop(resources);
        drop(context);
        result
    }
}

#[cfg(test)]
mod packet_layout_tests {
    use super::*;
    #[test]
    fn packet_layout_matches_core_midi_four_byte_packing() {
        assert_eq!(std::mem::align_of::<MIDIPacket>(), 4);
        assert_eq!(std::mem::size_of::<MIDIPacket>(), 268);
        assert_eq!(std::mem::offset_of!(MIDIPacket, data), 10);
        assert_eq!(std::mem::offset_of!(MIDIPacketList, packet), 4);
    }
}
