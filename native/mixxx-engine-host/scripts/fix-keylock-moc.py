"""Make Qt's generated includes refer to the same owned header overlays."""
from pathlib import Path
import re
import sys
build = Path(sys.argv[1])
headers = {'effectslot':'effects/effectslot.h','enginebuffer': 'engine/enginebuffer.h', 'readaheadmanager': 'engine/readaheadmanager.h',
           'enginebufferscale': 'engine/bufferscalers/enginebufferscale.h',
           'enginebufferscalest': 'engine/bufferscalers/enginebufferscalest.h',
           'enginebufferscalerubberband': 'engine/bufferscalers/enginebufferscalerubberband.h'}
for name, relative in headers.items():
    for file in (build / 'mixxx-lib_autogen').rglob(f'moc_{name}.cpp'):
        original = file.read_text()
        updated = re.sub(r'#include "[^"\n]*/' + name + r'\.h"',
                         '#include "' + str(build / 'junction-headers' / relative) + '"', original)
        if updated != original:
            file.write_text(updated)
