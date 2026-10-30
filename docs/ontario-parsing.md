# How parsing works for Ontario

Ontario publishes Hansards in two distinct HTML formats across the years.

## a. Modern format (most parliaments)

- `<h2>` → `OrderofBusiness`.
- `<h3>` / `<h4>` → `SubjectofBusiness`.
- `<p class="speakerStart">` containing `<strong>Speaker Name:</strong> ...`
  starts a new speaker turn.
- `<p class="Procedure">` is a procedural note.
- Other `<p>` tags continue the current speaker.

## b. Older format (32nd, 37th, 39th parliaments observed so far)

These files don't use `<h2>`/`<h3>`. Instead they style headings as paragraphs
with a `class` attribute that mimics table cells:

- `<p class="th">` → `OrderofBusiness` (high-level section, e.g. "STATEMENT
  BY THE MINISTRY").
- `<p class="td">` → `SubjectofBusiness` (specific topic, e.g. "ONTARIO
  TECHNOLOGY CENTRES").
- Speakers are still marked by `<strong>Name:</strong>` inside a paragraph.

The parser handles both formats in one pass — it checks paragraph class names
first, falls back to `<h2>`/`<h3>` headings, and finally treats everything
else as paragraph body. The mapping is applied to every document, no matter what parliament number it comes from. the class is a sufficient signal.

## Procedural vs speech

A row is `intervention_type="procedural"` (and `PersonSpeaking=None`) when
either:
- the paragraph is `class="Procedure"`, or
- there is no current speaker and the text matches the procedural-language
  regex (`Interjections`, `Applause`, `The Speaker:`, `Pursuant to ...`, etc.).

Otherwise it's `intervention_type="speech"` with the speaker name in
`PersonSpeaking`.

## c. Recorded divisions (votes)

When the House holds a recorded vote, the transcript lists the members who voted
on each side. Each side becomes **one `division` row**: `vote_direction`
(`aye`/`nay`), `vote_count` when printed, and the names in `voters`. The same
names, joined with `; `, go in `Intervention`. A semicolon is used because names
themselves can contain commas ("Smith, J.").

The rows around the division are unchanged. "The division bells rang..." stays a
`procedural` row, the Speaker's "All those in favour..." stays a `speech` row,
and the result line ("Motion agreed to") is `procedural` as before.

**Finding the marker (`_vote_marker`).** Every paragraph is checked for a
division marker *before* heading and speaker handling, so "AYES"/"NAYS" never
turn into headings, even under the ALL-CAPS heading fallback. A paragraph is a
marker when its whole text is:

- a side word on its own: `Ayes`, `Nays`, `Yeas` (singular or plural, any case;
  `yea` maps to `aye`), or
- a side word plus a count: `Ayes - 52`, `Nays: 31`. The count fills `vote_count`.

Pages that mark the side with `<p class="voteDirection">` are also caught by
that class, even when the text doesn't match.

**Collecting names (`_collect_division_voters`).** From the marker, the parser
walks forward over the following sibling elements and reads names from whatever
layout the page uses:

| Layout | Where the names come from |
|---|---|
| `<ul><li>` list | each `<li>` |
| `<table>` | each `<p class="votetext">` in it, else each `<td>` |
| one name per `<p>` | each paragraph |
| many names in one `<p>`, comma-separated | split on commas (see below) |

Blank paragraphs are skipped. The walk stops at the first of:

- the next marker (the other side),
- a heading (`h2`/`h3`/`h4`),
- a combined tally line such as `Ayes 52; nays 31.` (`VOTE_TALLY_RE`, older
  transcripts),
- a speaker label (`Name:`) or procedural text, meaning dialogue has resumed,
- any other element type.

Every element the walk used, and everything inside it, is recorded in
`consumed_ids`, and the main loop skips those. Without that, `<p class="votetext">`
cells nested in the table would be visited again by the main loop and appended
to the surrounding text a second time.

**Splitting comma-joined names (`_names_from_paragraph`).** A comma can separate
two voters ("Arnott, Bailey, Clark") or sit inside one name ("Smith, J."). The
rules:

- If a paragraph splits into **two or fewer** parts, it is treated as **one** name.
- Otherwise each part is a name. A part made only of initials (`INITIALS_RE`,
  e.g. `J. R.`) is glued back onto the previous name.

`_clean_voter_name` then strips trailing `;`/`,` and a sentence-final period, but
keeps the period of a trailing initial (`Smith, J.` stays as is).

**Known limitations**

- `vote_count` is `None` whenever the count isn't printed on the marker line.
  It is not computed from `len(voters)`, so consumers can tell "not printed"
  from "printed". Use `len(voters)` when you need a number.
- A combined tally line (`Ayes 52; nays 31.`) ends name collection but isn't
  parsed for counts. It is not a heading, speaker or procedural line, so it is
  appended as a continuation of whoever spoke last before the division.
- A comma-joined paragraph of exactly two surnames ("Arnott, Bailey") is read as
  one name, because it looks the same as "Last name, first name".
- A bare paragraph reading just `Aye.` or `Nay.` would be taken for a marker. In
  practice members' responses come with a label ("Some hon. members: Aye"), which
  doesn't match.
- Divisions are only recognised in this layout. Votes reported only in prose
  ("the motion was carried on the following division: ...") are not split into
  names.