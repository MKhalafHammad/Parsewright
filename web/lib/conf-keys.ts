// A plain label and one-line description for the .conf settings Parsewright writes. Static
// and display-only; an unknown key shows just its name.
type Info = { label: string; description: string };

const EXACT: Record<string, Info> = {
  LINE_BREAKER: { label: "Line breaker", description: "The pattern that marks where one event ends and the next begins." },
  SHOULD_LINEMERGE: { label: "Merge lines", description: "Whether Splunk glues lines back together into one event (off when the line breaker does the work)." },
  TRUNCATE: { label: "Maximum event length", description: "Events longer than this many bytes are cut off (0 means no limit)." },
  TIME_PREFIX: { label: "Text before the timestamp", description: "A pattern Splunk skips before it starts reading the timestamp." },
  TIME_FORMAT: { label: "Timestamp format", description: "How the timestamp is written, in strptime notation." },
  MAX_TIMESTAMP_LOOKAHEAD: { label: "Timestamp length", description: "How many characters after the prefix Splunk reads for the timestamp." },
  TZ: { label: "Timezone", description: "Applied when the timestamp carries no offset." },
  KV_MODE: { label: "Automatic key=value fields", description: "Whether Splunk pulls key=value pairs (or JSON) out on its own at search time." },
  INDEXED_EXTRACTIONS: { label: "Structured parsing at index time", description: "Parses JSON or CSV when the data is indexed." },
  CHARSET: { label: "Character set", description: "The text encoding of the source." },
  EVENT_BREAKER_ENABLE: { label: "Forwarder event breaking", description: "Lets a universal forwarder split the stream at event boundaries." },
  EVENT_BREAKER: { label: "Forwarder event breaker", description: "The boundary pattern the forwarder uses." },
  category: { label: "Category", description: "Where this sourcetype is listed in Splunk's sourcetype picker." },
  pulldown_type: { label: "Show in picker", description: "Whether the sourcetype appears in Splunk's picker." },
  description: { label: "Description", description: "Free text shown in Splunk." },
  REGEX: { label: "Pattern", description: "The regular expression this transform matches." },
  FORMAT: { label: "Field names", description: "Which captured group becomes which field." },
  SOURCE_KEY: { label: "Read from", description: "The field the pattern is applied to." },
  DEST_KEY: { label: "Write to", description: "Where the result is written (index-time transforms)." },
  DELIMS: { label: "Delimiters", description: "Characters that separate pairs, then keys from values." },
  FIELDS: { label: "Field list", description: "Field names for delimiter-based extraction." },
  MV_ADD: { label: "Keep repeated values", description: "Collect repeated matches as a multivalue field." },
  CLEAN_KEYS: { label: "Clean field names", description: "Replace characters Splunk does not allow in field names." },
  search: { label: "Matching search", description: "The search that defines which events belong to this eventtype." },
  priority: { label: "Priority", description: "Which eventtype wins when several match." },
  version: { label: "Version", description: "The add-on version." },
  label: { label: "Display name", description: "The add-on name shown in Splunk." },
  is_visible: { label: "Visible in the app menu", description: "Add-ons are normally hidden." },
  is_configured: { label: "Configured", description: "Skips Splunk's setup screen." },
  id: { label: "App id", description: "The add-on's folder name." },
  build: { label: "Build number", description: "Splunk uses it to refresh static files." },
  check_for_updates: { label: "Check for updates", description: "Whether Splunk looks for newer versions online." },
  state: { label: "Enabled", description: "Whether the add-on is enabled." },
  author: { label: "Author", description: "Shown in Splunk's app list." },
};

const PREFIX: [string, Info][] = [
  ["EXTRACT-", { label: "Field extraction", description: "A regular expression whose named groups become fields at search time." }],
  ["REPORT-", { label: "Field transform", description: "Applies a transforms.conf stanza at search time." }],
  ["TRANSFORMS-", { label: "Index-time transform", description: "Applies a transforms.conf stanza while indexing." }],
  ["FIELDALIAS-", { label: "Field alias", description: "Copies a field under its CIM name." }],
  ["EVAL-", { label: "Calculated field", description: "Computes a CIM field from other fields with an eval expression." }],
  ["LOOKUP-", { label: "Lookup", description: "Adds fields from a lookup table." }],
  ["SEDCMD-", { label: "Text rewrite", description: "Rewrites the raw text while indexing." }],
];

export function confKey(key: string): Info | null {
  if (Object.hasOwn(EXACT, key)) return EXACT[key]!;
  for (const [p, info] of PREFIX) {
    if (key.startsWith(p)) return { ...info, label: `${info.label}: ${key.slice(p.length)}` };
  }
  return null;
}

/** Keys whose value is a pattern or expression: exact characters matter, so monospace. */
export function isCode(key: string): boolean {
  return /^(LINE_BREAKER|TIME_PREFIX|TIME_FORMAT|REGEX|FORMAT|EVENT_BREAKER|search|SEDCMD-|EXTRACT-|EVAL-|FIELDALIAS-)/.test(key);
}
