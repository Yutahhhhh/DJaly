# DJ engine third-party notices

DJaly's optional Mixxx engine host links Mixxx 2.5.6 commit
`3ebac449e7e5fe2a0186596657696e87ce8b0e56`, licensed under
GPL-2.0-or-later. The adapter and build scripts shipped with DJaly form part of
the corresponding source for the distributed host. Process separation is not
treated as a license exemption.

The Rust simulator contains no Mixxx code. Its exact dependency versions are
recorded in `native/dj-engine-host/Cargo.lock`.

The release corresponding-source archive includes the complete pinned Mixxx
and Microsoft GSL trees, the DJaly adapter/build scripts, the build-environment
version record, Homebrew formula metadata (license and upstream source URLs),
and an inventory of bundled runtime files. Qt and the other packaged libraries
remain dynamically linked so recipients can replace compatible library builds.

Upstream license and source:

- https://github.com/mixxxdj/mixxx/blob/2.5.6/LICENSE
- https://github.com/mixxxdj/mixxx/tree/2.5.6
