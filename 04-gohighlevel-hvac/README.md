# 04 - GoHighLevel: HVAC service company build

A complete GoHighLevel deployment for a one-truck residential HVAC company, built as a portfolio demo. Everything in it is real and running: the phone number, texting, booking, follow-up, and review workflows. The company is not.

Live site: https://thatsautomatedhvac.com
Sub-account: That's Automated Heating and Air (locationId `dF6GpnV3NGdeZSjrnIRl`)

## What this proves

- A local service business can go from nothing to a working lead-to-review pipeline in one working day.
- The failure paths are handled, not just the happy path: SMS delivery failures fall back to email, unhappy customers never get a review request, STOP requests end every sequence.
- GHL's newer AI tooling (site generation, workflow drafting) is useful for first drafts and unreliable for edits. Section "What the AI got wrong" has the specifics.

## Build log (Sep 10, 2026)

| Time | What | Method |
|---|---|---|
| Morning | Fictional company name, domain thatsautomatedhvac.com registered (Namecheap) | manual |
| Morning | Sub-account created, LC Phone number bought (+1 334-539-0157) | manual |
| Midday | Custom fields, tags, opportunity field | API |
| Midday | Service Pipeline created, sample Marketing Pipeline deleted | Claude in Chrome |
| Midday | Domain connected in GHL, DNS added, verified | Claude in Chrome + manual DNS |
| Midday | HVAC Contact Form built | manual (form builder) |
| Afternoon | Service Call calendar, custom values | API |
| Afternoon | Website generated in AI Studio, revised, published, domain attached | manual (AI Studio) |
| Afternoon | Email sending domain mail.thatsautomatedhvac.com added, DNS at Namecheap | manual |
| Evening | Eight workflows built, all in draft | AI draft + manual fix |

Waiting on: A2P 10DLC brand and campaign approval (blocked on EIN confirmation letter), email domain verification.

## CRM spine

**Custom fields (contact)**
| Name | Key | Type | Options |
|---|---|---|---|
| Service Type | contact.service_type | dropdown | Repair, Maintenance, New installation, Not sure |
| Equipment | contact.equipment | text | |
| Lead Source | contact.lead_source | dropdown | Website form, Missed call, Facebook, Google, WhatsApp, Referral, Other |
| Preferred Contact Channel | contact.preferred_contact_channel | dropdown | Text, Call, Email, WhatsApp |
| SMS Consent | contact.sms_consent | checkbox | consent text baked into the label |

**Custom field (opportunity)**
| Name | Key | Type |
|---|---|---|
| Job Value | opportunity.job_value | money |

**Tags:** `stop-requested`, `replied-unhappy`, `review-sent`, `sms-failed`

**Pipeline: Service Pipeline**
New lead (20%) → Contacted (40%) → Booked (60%) → Job done (80%) → Review requested (90%) → Closed (100%)

**Custom values**
| Name | Merge tag | Value |
|---|---|---|
| Booking Link | `{{custom_values.booking_link}}` | https://api.leadconnectorhq.com/widget/bookings/thatsautomated-service-call |
| Review Link | `{{custom_values.review_link}}` | https://thatsautomatedhvac.com/review (placeholder) |

## Calendar: Service Call

- Type: Personal Booking (an Event-type calendar was created first via API and replaced, see gotchas)
- ID: `X0sZ4HrgX57wlVBhqfW7`, slug `thatsautomated-service-call`
- 60 min slots, 30 min buffer, 2 hours minimum notice, 30 days out, auto-confirm, one per slot
- Availability: Mon to Fri 8 to 5 (Saturday optional), America/Chicago
- Location: customer's address
- Google Calendar two-way sync on the owner's user

## Form: HVAC Contact Form

Form ID `9d480U5g2M6WjdDCgkO8`. Fields: first name, last name, phone (required), email, Service Type (required), Equipment, Preferred Contact Channel, SMS consent checkbox (required, unchecked by default, built-in GHL consent element), Privacy and Terms links. Lead Source is set by the New Lead Owner Alert workflow, not a hidden field; the form builder has no hidden-field option.

Consent text on the form:
> I agree to receive text messages from That's Automated Heating and Air about my inquiry, appointments, and service updates. Message frequency varies. Msg and data rates may apply. Reply STOP to opt out, HELP for help. See our Privacy Policy and Terms.

## Website

Generated with GHL AI Studio (Labs beta in the sub-account, pay-per-use since Sep 1, 2026), four pages: Home, Book a Visit, Privacy Policy, Terms of Service. The real GHL form and calendar are embedded; the AI's first draft built its own form and calendar widget and had to be told to swap them. Privacy and Terms carry the full SMS disclosure set carriers check for (frequency, rates, STOP, HELP, no third-party sharing, consent not a condition of purchase). Footer carries a demonstration disclaimer.

Cost: about $1 for generation plus one revision round.

## DNS (Namecheap)

| Host | Type | Value | Purpose |
|---|---|---|---|
| @ | A | 162.159.140.166 | site |
| www | CNAME | vibe.ludicrous.cloud | site (AI Studio host; classic Sites uses sites.ludicrous.cloud) |
| mail | CNAME/TXT | TODO: paste the DKIM, SPF, DMARC records GHL issued | email sending |

## Workflows

All eight are in draft until A2P clears. Names in GHL should match these (some were auto-named by the AI builder and need renaming).

| # | Name | Trigger | Purpose |
|---|---|---|---|
| 1 | Missed Call Text-Back | Missed incoming call | 30 s wait, STOP check, text with booking link, Lead Source = Missed call, opportunity to New lead, owner alert |
| 2 | Booking Confirmation and Reminders | Service Call confirmed | SMS + email confirmation, opportunity to Booked, reminders 24 h and 2 h before |
| 3 | Unbooked Lead Follow-Up | Form submitted, stage New lead | 3 texts over 5 days, each gated on "not yet Booked", stop on reply ON |
| 4 | Review Request | Stage Job done | 2 h wait, skip if tagged unhappy or stop, review text, tag, stage Review requested |
| 5 | SMS Fallback to Email | SMS delivery failed | tag sms-failed, resend by email, owner alert |
| 6 | New Lead Owner Alert | Form submitted | Lead Source = Website form, opportunity New lead, owner alert, acknowledgement text |
| 7 | Tag Stop Requests | SMS reply contains "stop" | tag stop-requested, remove from all workflows |
| 8 | Flag Unhappy Replies | SMS reply contains unhappy keywords | tag replied-unhappy, remove from Review Request, owner alert |

Full build spec with message text: `hvac-workflow-build-spec.md`.

## Costs so far

| Item | Cost |
|---|---|
| Domain | ~$12/yr |
| LC Phone number | ~$1.15/mo plus usage |
| AI Studio site | ~$1 one-time |
| AI workflow builder | free (beta) |
| A2P registration | ~$4 brand + ~$15 campaign one-time (pending) |

Voice AI receptionist and Conversation AI (not yet built) are the only recurring AI costs; both bill per use.

## Gotchas worth knowing

- **Calendar slugs are global across all of GHL.** `book`, `service`, `call` were all taken. Use the business name in the slug.
- **Event-type calendars have no team member** and do not sync to Google. Use Personal Booking for anything tied to a person. The API creates Event calendars readily; Personal ones need a staff user in the sub-account first.
- **Agency admins are not sub-account staff.** Until the user is added to the sub-account under Settings, Team, the calendar's team member dropdown is empty and the API returns zero users.
- **Deleted calendars keep their slug** for a while (soft delete).
- **Sample data toggle did not fully apply.** Five "(Example)" contacts and a Marketing Pipeline appeared anyway and were deleted.
- **A2P 10DLC "Sole Proprietor" brand type is for businesses without an EIN.** A sole proprietorship that has an EIN registers as Standard, legal name exactly as on the CP 575.
- **AI Studio's domain host differs from classic Sites.** The domain had to be disconnected from Settings, Domains and the www CNAME repointed.
- **The GHL AI workflow builder** drafts linear workflows well and mangles anything with branches on edit: it deleted If/Else nodes, wrapped checks in find-contact/find-opportunity multipath nodes, reordered waits, and rewrote message text. Use it for first drafts of 2, 5, 6; hand-build 1, 3, 4 and the helpers.
- **Most GHL screens run in a cross-origin iframe** (form builder, site builder, AI Studio, workflow editor, business profile), which browser automation cannot click into. Pipelines, domains, and the contacts list render in the main app and can be driven. The public API covers fields, tags, custom values, calendars, contacts, and reading workflows, but not pipelines, forms, workflows, sites, or the business profile.

## Still to do

- Rename workflows to the names above
- A2P brand + campaign (needs EIN letter): screenshot of the consent checkbox on the live site and the privacy URL are ready
- Verify email sending domain, paste records into the DNS table
- Run the email-only test plan, then the SMS test plan after approval
- Voice AI receptionist, Conversation AI, dashboard, snapshot, Loom
