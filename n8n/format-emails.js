// Разбор ответа MCP
function unwrapMcpPayload(raw) {
  if (!raw || typeof raw !== 'object') return {};
  if (raw.emails !== undefined || raw.events !== undefined || raw.is_initial !== undefined) return raw;
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

function looksLikeHtml(text) {
  const sample = String(text || '').slice(0, 8000);
  return /<\s*(?:html|head|body|style|table|div|p|span)\b/i.test(sample);
}

function decodeHtmlEntities(text) {
  return String(text || '')
    .replace(/&nbsp;/gi, ' ')
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&apos;/g, "'");
}

function dropCssArtifactLines(text) {
  return String(text || '')
    .split('\n')
    .filter((line) => {
      const trimmed = line.trim();
      if (!trimmed) return true;
      if (/^@media\b/i.test(trimmed)) return false;
      if (/^\s*[.#][\w-]+\s*\{/.test(trimmed)) return false;
      if (/\{[^}]*\}/.test(trimmed) && /!important|(?:^|[;\s])(?:margin|padding|font-size|line-height|display|width|height)\s*:/i.test(trimmed)) {
        return false;
      }
      return true;
    })
    .join('\n');
}

function stripHtml(html) {
  if (!html) return '';
  let text = String(html)
    .replace(/\r\n/g, '\n')
    .replace(/\r/g, '\n');

  text = text.replace(/<head[\s\S]*?<\/head>/gi, '');
  text = text.replace(/<style[\s\S]*?<\/style>/gi, '');
  text = text.replace(/<script[\s\S]*?<\/script>/gi, '');
  text = text.replace(/<!--[\s\S]*?-->/g, '');
  text = text.replace(/<!\[CDATA\[([\s\S]*?)\]\]>/gi, '$1');
  text = text.replace(/<br\s*\/?>/gi, '\n');
  text = text.replace(/<\/(?:p|div|tr|li|h[1-6]|table|td|th|blockquote)>/gi, '\n');
  text = text.replace(/<[^>]+>/g, '');
  text = decodeHtmlEntities(text);
  text = dropCssArtifactLines(text);
  text = text.replace(/[ \t]+\n/g, '\n');
  text = text.replace(/\n{3,}/g, '\n\n');
  return text.trim();
}

function parseIcalDate(raw) {
  const value = String(raw || '').trim();
  if (!value) return null;
  const compact = value.match(/^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})Z?$/);
  if (compact) {
    const [, y, m, d, hh, mm, ss] = compact;
    const iso = `${y}-${m}-${d}T${hh}:${mm}:${ss}${value.endsWith('Z') ? 'Z' : ''}`;
    const dateValue = new Date(iso);
    return Number.isNaN(dateValue.getTime()) ? null : dateValue;
  }
  const dateValue = new Date(value);
  return Number.isNaN(dateValue.getTime()) ? null : dateValue;
}

function extractMeetingFromIcs(text) {
  if (!text || !text.includes('BEGIN:VEVENT')) return null;
  const dtstart = text.match(/DTSTART(?:;[^:\r\n]*)?:([^\r\n]+)/i)?.[1];
  if (!dtstart) return null;
  const dtend = text.match(/DTEND(?:;[^:\r\n]*)?:([^\r\n]+)/i)?.[1];
  const location = text.match(/LOCATION:([^\r\n]+)/i)?.[1]?.replace(/\\n/g, ' ').replace(/\\,/g, ',');
  const start = parseIcalDate(dtstart);
  if (!start) return null;
  const end = dtend ? parseIcalDate(dtend) : null;
  return {
    start: start.toISOString(),
    end: end ? end.toISOString() : '',
    location: location || '',
  };
}

function formatMskTime(isoValue) {
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
  const dateValue = new Date(isoValue);
  if (Number.isNaN(dateValue.getTime())) return '?';
  return dateValue.toLocaleDateString('ru-RU', {
    timeZone: 'Europe/Moscow',
    day: 'numeric',
    month: 'short',
  });
}

function formatMeetingRange(startIso, endIso) {
  const dateStr = formatMskDate(startIso);
  const startTime = formatMskTime(startIso);
  if (!endIso) return `Встреча: ${dateStr}, ${startTime} МСК`;
  const endTime = formatMskTime(endIso);
  return `Встреча: ${dateStr}, ${startTime}–${endTime} МСК`;
}

function bodyForTelegram(email) {
  const maxLen = 3500;
  let plain = '';
  if (email.body) {
    const rawBody = String(email.body);
    plain = (email.body_is_html || looksLikeHtml(rawBody)) ? stripHtml(rawBody) : rawBody;
  } else if (email.preview) {
    plain = String(email.preview);
  }
  plain = plain.replace(/BEGIN:VCALENDAR[\s\S]*?END:VCALENDAR/g, '').trim();
  if (plain.length > maxLen) return plain.slice(0, maxLen) + '…';
  return plain;
}

function isMeetingLike(email, bodyText, meeting) {
  if (meeting) return true;
  const haystack = `${email.subject || ''}\n${bodyText}`.toLowerCase();
  return /telemost\.yandex|zoom\.us|meet\.google|teams\.microsoft|begin:vevent|приглашение|invitation|meeting request/.test(haystack);
}

const emailMcpItems = $('MCP: exchange_get_new_emails').all();
const emailData = unwrapMcp(emailMcpItems.length ? emailMcpItems : $input.all());
const emails = emailData.emails || [];

if (emailData.is_initial) {
  return [{ json: { type: 'none' } }];
}

const linkPatterns = [
  /https:\/\/[\w.-]*zoom\.us\/[^\s<"]+/gi,
  /https:\/\/telemost\.yandex\.(?:ru|com)\/[^\s<"]+/gi,
  /https:\/\/meet\.google\.com\/[^\s<"]+/gi,
  /https:\/\/teams\.microsoft\.com\/[^\s<"]+/gi,
];

const messages = [];

for (const email of emails) {
  const bodyText = `${email.body || ''} ${email.preview || ''}`;
  let meeting = email.meeting || extractMeetingFromIcs(bodyText) || null;
  const meetingLike = isMeetingLike(email, bodyText, meeting);
  const readMark = email.read ? '📖' : (meetingLike ? '📅' : '📩');

  let text = `${readMark} <b>${escHtml(email.subject) || '(без темы)'}</b>\n`;
  text += `👤 ${escHtml(email.from)}\n`;

  if (meeting?.start) {
    text += `🕐 ${formatMeetingRange(meeting.start, meeting.end)}\n`;
    if (meeting.location) text += `📍 ${escHtml(meeting.location)}\n`;
  }

  if (email.date) {
    const dateValue = new Date(email.date);
    const dateStr = dateValue.toLocaleString('ru-RU', {
      timeZone: 'Europe/Moscow',
      day: 'numeric',
      month: 'short',
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
    });
    text += `📬 Получено: ${dateStr} МСК\n`;
  }

  const links = [];
  for (const pattern of linkPatterns) {
    const matches = bodyText.match(pattern);
    if (matches) links.push(...matches);
  }
  if (links.length > 0) {
    text += `\n🔗 Ссылки:\n`;
    for (const link of [...new Set(links)]) {
      text += `${link}\n`;
    }
  }

  const bodyPlain = bodyForTelegram(email);
  if (bodyPlain) {
    text += `\n\n${escHtml(bodyPlain)}`;
  }

  messages.push({ type: 'email', text });

  if (email.has_attachments && email.id) {
    messages.push({
      type: 'attachment_fetch',
      item_id: email.id,
      subject: email.subject || '(без темы)',
    });
  }
}

return messages.length > 0
  ? messages.map((message) => ({ json: message }))
  : [{ json: { type: 'none' } }];
