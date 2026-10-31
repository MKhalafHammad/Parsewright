# lab/

Files the bundled Splunk needs that cannot be committed. Mounted read-only into the `splunk`
container at `/opt/parsewright/lab`. `*.tgz` is git-ignored.

**The Splunk Common Information Model add-on** (required: the CIM stage checks data models).
It is free but licensed by Splunk, so it is not redistributed here:

1. Download it from Splunkbase (a free account is enough): search for
   "Splunk Common Information Model (CIM)".
2. Save the `.tgz` in this folder, keeping its name
   (`splunk-common-information-model-cim_<version>.tgz`).
3. Run `make up`. The bootstrap installs it once and points its index macros at `pw_*`.
