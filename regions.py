"""Disc identification shared by extraction and the viewer."""
import re
REGIONS={'SCUS_976.15':('ntscu','NTSC-U'),'SCES_550.19':('pal','PAL'),'SCPS_151.20':('ntscj','NTSC-J')}

def detect_region(config):
    match=re.search(r'(SC[UEP]S_\d{3}\.\d{2})',config,re.I)
    serial=match[1].upper() if match else None
    key,label=REGIONS.get(serial,('unknown','Unknown region'))
    return dict(id=key,label=label,serial=serial)
