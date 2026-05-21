function unwrapMcpPayload(raw) {
  if (!raw || typeof raw !== 'object') return {};
  if (raw.added !== undefined || raw.changed !== undefined || raw.deleted !== undefined || raw.events !== undefined || raw.is_initial !== undefined) {
    return raw;
  }
  if (Array.isArray(raw.content) && raw.content.length > 0) {
    const textPayload = raw.content[0].text;
    if (textPayload && typeof textPayload === 'object') return textPayload;
    if (typeof textPayload === 'string') {
      try { return JSON.parse(textPayload); } catch { return {}; }
    }
  }
  return raw;
}

function unwrapMcp(nodeItems) {
  const item = (nodeItems && nodeItems[0]) ? nodeItems[0] : null;
  if (!item) return {};
  return unwrapMcpPayload(item.json ?? item);
}

function escHtml(value) {
  return String(value || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function formatMskTime(isoValue) {
  if (!isoValue) return '??:??';
  const dateValue = new Date(isoValue);
  if (Number.isNaN(dateValue.getTime())) return '??:??';
  return dateValue.toLocaleTimeString('ru-RU', {
    timeZone: 'Europe/Moscow',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  });
}

function formatMskDate(isoValue) {
  if (!isoValue) return '?';
  const dateValue = new Date(isoValue);
  if (Number.isNaN(dateValue.getTime())) return '?';
  return dateValue.toLocaleDateString('ru-RU', {
    timeZone: 'Europe/Moscow',
    day: 'numeric',
    month: 'short',
  });
}

function sanitizeUid(rawUid) {
  return String(rawUid || '').replace(/[^a-zA-Z0-9@._-]/g, '_');
}

function toICalUtc(isoValue) {
  if (!isoValue) return '';
  return new Date(isoValue).toISOString().replace(/[-:]/g, '').replace(/\.\d{3}/, '');
}

function icalEsc(value) {
  return String(value || '').replace(/\\/g, '\\\\').replace(/;/g, '\\;').replace(/,/g, '\\,').replace(/[\r\n]+/g, '\\n');
}

function buildICal(event) {
  const uid = sanitizeUid(event.uid || event.id || `ews-${Date.now()}`);
  const dtstart = toICalUtc(event.start);
  const dtend = toICalUtc(event.end);
  const now = toICalUtc(new Date().toISOString());

  let ical = 'BEGIN:VCALENDAR\r\n';
  ical += 'VERSION:2.0\r\n';
  ical += 'PRODID:-//Exchange MCP//EN\r\n';
  ical += 'BEGIN:VEVENT\r\n';
  ical += `UID:${uid}\r\n`;
  ical += `DTSTAMP:${now}\r\n`;
  ical += `DTSTART:${dtstart}\r\n`;
  ical += `DTEND:${dtend}\r\n`;
  ical += `SUMMARY:${icalEsc(event.subject)}\r\n`;
  if (event.location) ical += `LOCATION:${icalEsc(event.location)}\r\n`;
  if (event.organizer) ical += `ORGANIZER:mailto:${icalEsc(event.organizer)}\r\n`;
  const attendees = Array.isArray(event.attendees) ? event.attendees : [];
  for (const attendee of attendees) {
    const address = typeof attendee === 'string' ? attendee : (attendee.email || attendee.name || '');
    if (address) ical += `ATTENDEE:mailto:${icalEsc(address)}\r\n`;
  }
  if (event.body) ical += `DESCRIPTION:${icalEsc(String(event.body).substring(0, 500))}\r\n`;
  if (event.all_day) ical += 'X-MICROSOFT-CDO-ALLDAYEVENT:TRUE\r\n';
  ical += 'END:VEVENT\r\n';
  ical += 'END:VCALENDAR\r\n';
  return { uid, ical };
}

function formatEventText(event, prefix) {
  const startTime = formatMskTime(event.start);
  const endTime = formatMskTime(event.end);
  const dateStr = formatMskDate(event.start);

  let text = `${prefix} <b>${escHtml(event.subject || '(без темы)')}</b>\n`;
  text += `🕐 ${dateStr}, ${startTime}–${endTime} МСК\n`;
  if (event.location) text += `📍 ${escHtml(event.location)}\n`;
  if (event.organizer) text += `👤 ${escHtml(event.organizer)}\n`;

  const searchableText = `${event.body || ''} ${event.location || ''}`;
  const meetingLink = searchableText.match(
    /https:\/\/[\w.-]*(?:zoom\.us|telemost\.yandex|meet\.google|teams\.microsoft)[^\s<"]*/i,
  );
  if (meetingLink) text += `🔗 ${meetingLink[0]}\n`;

  const attendees = Array.isArray(event.attendees) ? event.attendees : [];
  if (attendees.length > 0) {
    const names = attendees
      .map((entry) => (typeof entry === 'string' ? entry : (entry.name || entry.email)))
      .filter(Boolean)
      .slice(0, 5);
    if (names.length > 0) text += `👥 ${escHtml(names.join(', '))}\n`;
  }

  if (event.body) {
    const bodyPlain = String(event.body).replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim();
    if (bodyPlain) text += `\n\n${escHtml(bodyPlain.slice(0, 800))}`;
  }

  return text;
}

const eventMcpItems = $('MCP: exchange_get_new_events').all();
const eventData = unwrapMcp(eventMcpItems.length ? eventMcpItems : $input.all());

if (eventData.is_initial) {
  return [{ json: { type: 'none' } }];
}

const addedEvents = Array.isArray(eventData.added) ? eventData.added : (eventData.events || []);
const changedEvents = Array.isArray(eventData.changed) ? eventData.changed : [];
const deletedEvents = Array.isArray(eventData.deleted) ? eventData.deleted : [];
const output = [];

for (const event of addedEvents) {
  output.push({ type: 'tg_event', text: formatEventText(event, '📅') });
  const { uid, ical } = buildICal(event);
  output.push({ type: 'caldav', uid, ical });
}

for (const event of changedEvents) {
  output.push({ type: 'tg_event', text: formatEventText(event, '✏️') });
  const { uid, ical } = buildICal(event);
  output.push({ type: 'caldav', uid, ical });
}

for (const deleted of deletedEvents) {
  const uid = sanitizeUid(deleted.uid || deleted.server_id || '');
  if (!uid) continue;
  const subject = deleted.subject || '(без темы)';
  output.push({
    type: 'tg_event',
    text: `❌ <b>Отмена:</b> ${escHtml(subject)}`,
  });
  output.push({ type: 'caldav_delete', uid });
}

return output.length > 0
  ? output.map((row) => ({ json: row }))
  : [{ json: { type: 'none' } }];
