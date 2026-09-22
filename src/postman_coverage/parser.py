"""Parse YAML filenames into structured spec identifiers.

The convention is `<Service>[-<version>]_<CORE>[<sep><Action>[_<Type>]].yaml`
but real filenames vary in casing and separators. The parser anchors on the
`_<CORE>` token (the first uppercase run after an underscore that looks like
a core code) and treats everything before it as the service name. All of
these parse:

    AcctService-11.0.0_PRM-Add_DDA.yaml
    AddressService-11.0.0_PRM.yaml                       # no action / type
    AcctService-11.0.0_DNA-Add_DDA_SDA_CDA.yaml          # multi-type
    XferService-11.0.0_DNA_ListInq.yaml                  # `_` separator
    region-service-11.0.0_PRM.yaml                       # lowercase-hyphenated
    Reinvestment-Service-11.0.0_SIG.yaml                 # hyphen + CamelCase
    ach-external_transfer_service-11.0.0_SIG.yaml        # mixed separators
    TellerSignOn-11.0.0_SIG.yaml                         # doesn't end in "Service"
    HostLogon_DNA.yaml                                   # no version
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_FILENAME_RE = re.compile(
    r"""
    ^
    (?P<service>[A-Za-z][A-Za-z0-9_\-]*?)          # anything up to the core anchor
    (?:-(?P<version>\d+(?:\.\d+)*))?               # optional -<version>
    _
    (?P<core>[A-Z][A-Z0-9]{1,10})                  # uppercase core code
    (?:                                            # optional -<action>[_<type>]
        [-_]
        (?P<action>[A-Za-z]+)
        (?:
            _
            (?P<type>[A-Za-z0-9]+(?:_[A-Za-z0-9]+)*)
        )?
    )?
    \.ya?ml
    $
    """,
    re.VERBOSE,
)


@dataclass(frozen=True)
class YamlSpec:
    filename: str
    service: str
    version: str | None
    core: str
    action: str | None
    type: str | None

    @property
    def display(self) -> str:
        parts: list[str] = [self.service]
        if self.action:
            parts.append(self.action)
        if self.type:
            parts.append(self.type)
        return " / ".join(parts)


def parse_filename(filename: str) -> YamlSpec | None:
    m = _FILENAME_RE.match(filename.strip())
    if not m:
        return None
    return YamlSpec(
        filename=filename,
        service=m.group("service"),
        version=m.group("version"),
        core=m.group("core"),
        action=m.group("action"),
        type=m.group("type"),
    )
