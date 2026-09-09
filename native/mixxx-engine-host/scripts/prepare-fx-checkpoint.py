"""Friend-only hooks in owned header overlays; never edit the pinned checkout."""
from pathlib import Path
import re
import sys
source,output=map(Path,sys.argv[1:3])
headers={
 'effects/effectslot.h':['EffectSlot'],
 'effects/backends/effectprocessor.h':['EffectProcessorImpl'],
 'engine/effects/engineeffect.h':['EngineEffect'],
 'engine/effects/engineeffectchain.h':['EngineEffectChain'],
 'effects/backends/builtin/autopaneffect.h':['RampedSample'],
 'engine/filters/enginefilterpansingle.h':['EngineFilterPanSingle'],
 'effects/backends/builtin/pitchshifteffect.h':['PitchShiftEffect'],
}
for relative,names in headers.items():
 text=(source/relative).read_text()
 for name in names:
  text,count=re.subn(r'(class '+name+r'[^;{]*\{)',r'\1\n    friend class ::junction::fx::Access;',text,count=1)
  assert count==1,name
 text='namespace junction { namespace fx { class Access; } }\n'+text
 target=output/relative;target.parent.mkdir(parents=True,exist_ok=True)
 if not target.exists() or target.read_text()!=text:target.write_text(text)
