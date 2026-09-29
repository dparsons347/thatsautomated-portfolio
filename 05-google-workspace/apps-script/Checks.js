/**
 * Manual checks, run from the editor. Kept in their own file so the editor's
 * Run button defaults to them when this file is open.
 */
/** Run from the editor after setting CHAT_WEBHOOK_URL to confirm Chat posts arrive. */
function testChat() {
  var ok = postChat_('Oakline intake is connected to this space.');
  return ok ? 'Posted to Chat.' : 'Chat post failed or CHAT_WEBHOOK_URL is not set; see the log.';
}
