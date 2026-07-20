(function attachHandoffIntent(root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.HandoffIntent = api;
}(typeof globalThis !== 'undefined' ? globalThis : this, function createHandoffIntent() {
  const TARGET = '(?:人工客服|真人客服|人工|真人|客服|营养师)';
  const VERB = '(?:转接|切换|联系|转|找)';
  const POLITE = '(?:请|麻烦你?|帮我|给我|能否|可以|可不可以)';
  const SUBJECT = '(?:我(?:还是|仍然|仍)?(?:想要?|要)|我要|我想找)';
  const MODIFIER = '(?:直接|现在|马上|立即|还是|仍然|仍)?';
  const LINK = '(?:一下|到|给)?';
  const ENDING = '(?:处理|服务|咨询|回答)?(?:一下|吧|吗|可以吗|行吗|好吗)?';

  const exactPattern = /^(?:转人工|转接人工|人工客服|人工咨询|真人客服|真人咨询|联系营养师|找客服|找营养师)$/;
  const commandPattern = new RegExp(`^(?:(?:${POLITE}|${SUBJECT}))?${MODIFIER}${VERB}${LINK}${TARGET}${ENDING}$`);
  const directTargetPattern = new RegExp(`^(?:${SUBJECT})${MODIFIER}${TARGET}${ENDING}$`);
  const trailingCommandPattern = new RegExp(`(?:${POLITE}|${SUBJECT})${MODIFIER}${VERB}${LINK}${TARGET}${ENDING}$`);

  function normalizeClause(value) {
    return String(value || '')
      .normalize('NFKC')
      .replace(/\s+/g, '')
      .replace(/[。！!？?；;]+$/g, '');
  }

  function isExplicitHandoffIntent(value) {
    const source = String(value || '').trim();
    if (!source || source.length > 120) return false;
    const clauses = source.split(/[，,。！!？?；;\n]+/).map(normalizeClause).filter(Boolean);
    const lastClause = clauses[clauses.length - 1] || normalizeClause(source);
    if (!lastClause) return false;
    return exactPattern.test(lastClause)
      || commandPattern.test(lastClause)
      || directTargetPattern.test(lastClause)
      || trailingCommandPattern.test(lastClause);
  }

  return { isExplicitHandoffIntent };
}));
