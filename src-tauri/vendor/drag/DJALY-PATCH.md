# DJaly compatibility patch

Vendored from crates.io drag 2.1.1, retaining upstream Apache-2.0/MIT licenses.

Only behavior change: in src/platform_impl/macos/mod.rs, external application
Copy drags advertise NSDragOperationCopy | NSDragOperationGeneric. JUCE targets
return Generic when they accept files; the previous Copy-only mask excluded
that operation. Move and internal application drags, and other OS backends,
are unchanged. No move/delete operation is added to Copy drags.

Upstream JUCE evidence:
https://github.com/juce-framework/JUCE/blob/master/modules/juce_gui_basics/native/juce_NSViewComponentPeer_mac.mm
(search draggingUpdated / NSDragOperationGeneric).

Remove this patch when upstream drag supports compatible external operation masks.
