// Exits 0 when some application is recording, 1 when nothing is.
//
// Every input device is checked rather than just the default one: conferencing apps
// often pick a specific microphone, and the default device would then look idle.
//
// Reading kAudioDevicePropertyDeviceIsRunningSomewhere needs no microphone permission -
// it reports that a device is in use, never what is being said.

import CoreAudio
import Foundation

func property(_ selector: AudioObjectPropertySelector,
              scope: AudioObjectPropertyScope = kAudioObjectPropertyScopeGlobal)
    -> AudioObjectPropertyAddress {
    AudioObjectPropertyAddress(mSelector: selector,
                               mScope: scope,
                               mElement: kAudioObjectPropertyElementMain)
}

func allDevices() -> [AudioDeviceID] {
    var address = property(kAudioHardwarePropertyDevices)
    var size: UInt32 = 0
    guard AudioObjectGetPropertyDataSize(
        AudioObjectID(kAudioObjectSystemObject), &address, 0, nil, &size) == noErr else {
        return []
    }
    let count = Int(size) / MemoryLayout<AudioDeviceID>.size
    var devices = [AudioDeviceID](repeating: 0, count: count)
    guard AudioObjectGetPropertyData(
        AudioObjectID(kAudioObjectSystemObject), &address, 0, nil, &size, &devices) == noErr else {
        return []
    }
    return devices
}

func hasInput(_ device: AudioDeviceID) -> Bool {
    var address = property(kAudioDevicePropertyStreamConfiguration, scope: kAudioObjectPropertyScopeInput)
    var size: UInt32 = 0
    guard AudioObjectGetPropertyDataSize(device, &address, 0, nil, &size) == noErr, size > 0 else {
        return false
    }
    let buffer = UnsafeMutableRawPointer.allocate(byteCount: Int(size), alignment: 16)
    defer { buffer.deallocate() }
    guard AudioObjectGetPropertyData(device, &address, 0, nil, &size, buffer) == noErr else {
        return false
    }
    let list = buffer.assumingMemoryBound(to: AudioBufferList.self)
    return UnsafeMutableAudioBufferListPointer(list).contains { $0.mNumberChannels > 0 }
}

func isRunning(_ device: AudioDeviceID) -> Bool {
    var address = property(kAudioDevicePropertyDeviceIsRunningSomewhere)
    var running: UInt32 = 0
    var size = UInt32(MemoryLayout<UInt32>.size)
    guard AudioObjectGetPropertyData(device, &address, 0, nil, &size, &running) == noErr else {
        return false
    }
    return running != 0
}

let busy = allDevices().contains { hasInput($0) && isRunning($0) }
print(busy ? "busy" : "idle")
exit(busy ? 0 : 1)
