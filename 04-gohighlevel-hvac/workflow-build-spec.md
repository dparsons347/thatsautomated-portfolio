# HVAC demo: workflow build spec

Six workflows for the That's Automated Heating and Air sub-account. Build in this order. Test each with email until A2P clears, then re-test with SMS from your own phone.

Conventions used below:
- `{{custom_values.booking_link}}` and `{{custom_values.review_link}}` already exist.
- Every workflow gets one "Internal Notification" step on failure paths so nothing fails silently. That is the thing the Loom sells.
- Every SMS is under 160 characters and starts with the business name so it passes the campaign sample messages you submitted.
- Menu labels in the workflow editor drift. Where a label is given, look for the nearest match.

Before building: Automation, Workflows, Create Workflow, Start from Scratch. Name it exactly as shown so the README and Loom script match.

---

## 1. Missed Call Text-Back

**Trigger:** Call Status. Filter: Call status is Missed, Direction is Incoming. (If your editor shows "Missed Call" as its own trigger, use that.)

**Actions, in order:**
1. Wait 30 seconds. (Gives you time to call back yourself before the text goes.)
2. If/Else. Condition: Contact tag includes `stop-requested`. If yes, End.
3. Send SMS:
   > That's Automated Heating and Air: Sorry we missed your call. Book a visit here: {{custom_values.booking_link}} or reply and we will call you back. Reply STOP to opt out.
4. Update Contact Field: Lead Source = Missed call.
5. Create/Update Opportunity: pipeline Service Pipeline, stage New lead, name `{{contact.name}} - missed call`. Set "Do not create if one already exists" (or the equivalent "update existing" option) so a repeat caller does not get two opportunities.
6. Internal Notification to you: `Missed call from {{contact.phone}}. Text-back sent.`

**Settings (gear icon):** Allow re-entry: Yes (a customer can miss you twice). Stop on reply: No (this is a single message, not a sequence).

**Failure branch for the Loom:** the SMS Fallback workflow (#5) handles a failed send; nothing extra here.

---

## 2. Booking Confirmation and Reminders

**Trigger:** Appointment Status. Filter: Calendar is Service Call, Appointment status is Confirmed.

**Actions:**
1. Send SMS immediately:
   > That's Automated Heating and Air: You are booked for {{appointment.start_time}}. Reply here if you need to change it. Reply STOP to opt out.
2. Send Email (same content, as the fallback and the pre-A2P test path). Subject: `Your visit is booked for {{appointment.start_time}}`.
3. Update Contact Field: Lead Source = Website form only if it is empty (use If/Else: Lead Source is empty, then set). Skip if your editor cannot test "is empty"; the form workflow (#6) covers it.
4. Create/Update Opportunity: Service Pipeline, stage Booked, same "update existing" setting as workflow 1.
5. Wait: until 24 hours before `{{appointment.start_time}}` (Wait step, type Event/Appointment Time, 1 day before).
6. Send SMS:
   > That's Automated Heating and Air: Reminder, your technician is scheduled for tomorrow at {{appointment.only_start_time}}. Reply STOP to opt out.
7. Wait: until 2 hours before the appointment.
8. Send SMS:
   > That's Automated Heating and Air: We are on for today at {{appointment.only_start_time}}. See you soon.

**Settings:** Allow re-entry: Yes. Add a second trigger for Appointment status is Cancelled that goes straight to End, or build a small separate "Cancelled" branch that sends one SMS and moves the opportunity back to Contacted. Keep it simple; the Loom does not show cancellation.

---

## 3. Unbooked Lead Follow-Up

This is the one that shows "stop on reply" on camera.

**Trigger:** Two triggers into the same workflow: (a) Form Submitted, form is HVAC Contact Form. (b) Pipeline Stage Changed, stage is New lead.

**Actions:**
1. Wait 1 hour.
2. If/Else: Contact has an appointment on Service Call in the next 30 days (condition "Appointment exists" or check opportunity stage is Booked). If yes, End.
3. Send SMS (touch 1):
   > That's Automated Heating and Air: Thanks for reaching out. Want to pick a time? {{custom_values.booking_link}} Or reply here with what works. Reply STOP to opt out.
4. Wait 2 days.
5. Same If/Else as step 2. If booked, End.
6. Send SMS (touch 2):
   > That's Automated Heating and Air: Still need help with your system? Reply with a good time to call or book here: {{custom_values.booking_link}}
7. Wait 2 days.
8. Same check.
9. Send SMS (touch 3):
   > That's Automated Heating and Air: Last note from us. If you need service later, this link always works: {{custom_values.booking_link}} Take care.
10. Update Opportunity: stage Contacted.

**Settings (this is the important part):**
- Stop on reply: **Yes**. This is the setting that ends the sequence the moment the customer texts back. In the Loom, reply from your phone after touch 1 and show the workflow status flip to ended.
- Allow re-entry: No.

**STOP handling:** GHL handles the literal word STOP at the carrier level and sets DND automatically. To make it visible for the Loom, add a separate tiny workflow, "Tag Stop Requests": trigger Customer Replied, filter reply contains `stop` (case-insensitive), action Add Tag `stop-requested`, action Remove from all workflows. Workflows 1 and 4 check that tag.

---

## 4. Review Request

**Trigger:** Pipeline Stage Changed. Pipeline Service Pipeline, stage is Job done.

**Actions:**
1. Wait 2 hours.
2. If/Else: Contact tag includes `replied-unhappy` OR `stop-requested`. If yes: Internal Notification `Review request skipped for {{contact.name}} (tagged)`, then End.
3. Send SMS:
   > That's Automated Heating and Air: Thanks for choosing us. If you have a minute, a quick review helps a lot: {{custom_values.review_link}} Reply STOP to opt out.
4. Add Tag `review-sent`.
5. Update Opportunity: stage Review requested.

**The unhappy-reply branch (built as a separate workflow, "Flag Unhappy Replies"):**
- Trigger: Customer Replied, channel SMS.
- If/Else: message contains any of `terrible`, `bad`, `unhappy`, `not happy`, `problem`, `still not working`, `disappointed`, `refund`, `worst`. (Keyword branch, not AI; keep it explainable.)
- If yes: Add Tag `replied-unhappy`, Remove Contact from workflow Review Request, Internal Notification to you: `Unhappy reply from {{contact.name}}: {{message.body}}`.

In the Loom: move a test contact to Job done, reply "this was terrible" from your phone inside the 2-hour wait, show the review SMS never sends and the owner alert fires.

**Settings:** Allow re-entry: No (one review ask per job). If you want re-entry per job later, key it on the opportunity instead.

---

## 5. SMS Fallback to Email

**Trigger:** SMS Status (or "Message Status" / "SMS Delivery"). Filter: status is Failed or Undelivered.

**Actions:**
1. Add Tag `sms-failed`.
2. Send Email. Subject: `We tried to text you`. Body: `We tried to reach you by text but it did not go through. Here is what we sent: {{message.body}}. Reply to this email or call +1 (334) 539-0157.`
3. Internal Notification: `SMS to {{contact.phone}} failed. Email fallback sent. Check the number.`

**Settings:** Allow re-entry: Yes.

**Loom test:** set a test contact's phone to a number that cannot receive SMS (a landline you own, or your office line), fire workflow 1 by any trigger, show the tag and the email.

---

## 6. New Lead Owner Alert (and form housekeeping)

**Trigger:** Form Submitted, form is HVAC Contact Form.

**Actions:**
1. Update Contact Field: Lead Source = Website form. (This replaces the hidden field the form builder would not give us.)
2. Create/Update Opportunity: Service Pipeline, stage New lead, name `{{contact.name}} - {{contact.service_type}}`, "update existing" on.
3. Internal Notification to you (email and app): `New lead: {{contact.name}}, {{contact.phone}}, {{contact.service_type}}. Equipment: {{contact.equipment}}. Prefers {{contact.preferred_contact_channel}}.`
4. Send SMS acknowledgement to the contact:
   > That's Automated Heating and Air: Got your message. We will text or call you back shortly. Reply STOP to opt out.

**Settings:** Allow re-entry: Yes.

Note: workflow 3 also triggers on form submission. That is intended; #6 handles the instant response and the alert, #3 handles the follow-up sequence an hour later.

---

## Test plan (pre-A2P, email only)

Temporarily swap each Send SMS for Send Email, or add an email step beside each SMS, and run:

1. Submit the site form with your own details. Expect: opportunity in New lead, owner alert, acknowledgement email (from #6), then one hour later the first follow-up (from #3).
2. Book through the calendar. Expect: confirmation (from #2), follow-up sequence ends at the next check.
3. Move the opportunity to Job done. Expect: review email after 2 hours.
4. Reply to any thread with "this was terrible" while the review wait is running. Expect: tag, alert, no review email.

Once A2P clears, put the SMS steps back and rerun 1 through 4 from your phone. Record the second run.

---

## What to screenshot as you go (for the site page and README)

- Each workflow's canvas, zoomed to fit.
- The Stop on reply toggle on workflow 3.
- The keyword branch on Flag Unhappy Replies.
- A workflow execution log showing an ended run after a reply.
