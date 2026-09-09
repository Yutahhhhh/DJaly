"""Pinned source hooks for typed R2 state access; algorithms remain unchanged."""
import hashlib
from pathlib import Path
import re
import sys
import tarfile
root = Path(sys.argv[1])
adapter = Path(sys.argv[2]).resolve()
hooks = {'rubberband/RubberBandStretcher.h':['RubberBandStretcher'], 'src/faster/R2Stretcher.h':['R2Stretcher'],
 'src/common/Resampler.h':['Resampler'], 'src/common/StretchCalculator.h':['StretchCalculator'],
 'src/faster/CompoundAudioCurve.h':['CompoundAudioCurve'], 'src/faster/PercussiveAudioCurve.h':['PercussiveAudioCurve'],
 'src/common/MovingMedian.h':['MovingMedian'], 'src/common/SingleThreadRingBuffer.h':['SingleThreadRingBuffer'],
 'src/common/RingBuffer.h':['RingBuffer']}
archive=root/'source.tar.bz2'
assert hashlib.sha256(archive.read_bytes()).hexdigest()=='af050313ee63bc18b35b2e064e5dce05b276aaf6d1aa2b8a82ced1fe2f8028e9'
with tarfile.open(archive) as source:
 for item in source.getmembers():
  relative=Path(item.name).relative_to('rubberband-4.0.0')
  if not item.isfile():continue
  assert '..' not in relative.parts
  data=source.extractfile(item).read()
  key=str(relative)
  names=hooks.get(key,[])
  if key=='src/RubberBandStretcher.cpp':names=['RubberBandStretcher::Impl']
  if key=='src/common/Resampler.cpp':names=['D_SRC']
  if names:
   text=data.decode()
   for name in names:
    text,count=re.subn(r'(class\s+(?:RUBBERBAND_DLLEXPORT\s+)?'+re.escape(name)+r'[^;{]*\{)',r'\1\n    friend class ::junction::rb::Access;',text,count=1)
    assert count==1,name
   data=('namespace junction { namespace rb { class Access; } }\n'+text).encode()
  if key=='src/RubberBandStretcher.cpp':data+=f'\n#include "{adapter}/rubberband_wrapper.inc"\n'.encode()
  if key=='src/common/Resampler.cpp':data+=f'\n#include "{adapter}/rubberband_resampler.inc"\n'.encode()
  target=root/'source'/relative;target.parent.mkdir(parents=True,exist_ok=True)
  if not target.exists() or target.read_bytes()!=data:target.write_bytes(data)
archive=root/'samplerate.tar.xz'
assert hashlib.sha256(archive.read_bytes()).hexdigest()=='3258da280511d24b49d6b08615bbe824d0cacc9842b0e4caf11c52cf2b043893'
with tarfile.open(archive) as source:
 common=source.extractfile('libsamplerate-0.2.2/src/common.h').read()
 sinc=source.extractfile('libsamplerate-0.2.2/src/src_sinc.c').read().decode()
 # Exact pinned field declaration, with no function pointers copied to wire.
 match=re.search(r'typedef struct\s*\{\s*int\s+sinc_magic_marker.*?\} SINC_FILTER ;',sinc,re.S);assert match
 data=('typedef float coeff_t;\n'+match[0]).encode()
 target=root/'private';target.mkdir(exist_ok=True)
 for name,content in [('common.h',common),('sinc_fields.h',data)]:
  file=target/name
  if not file.exists() or file.read_bytes()!=content:file.write_bytes(content)
