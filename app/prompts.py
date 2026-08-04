"""Prompt construction and output guardrails.

The guardrail matters more than the prompt. A model told "don't invent numbers"
still occasionally invents them; a post-check that compares every digit in the
answer against the retrieved context cannot.
"""

from __future__ import annotations

import re
from datetime import date

CONTACT = "info@anu.edu.eg"
CONTACT_PAGE = "https://anu.edu.eg/ar/contact"

FALLBACK = (
    "معنديش المعلومة دي مؤكدة في مصادر الجامعة، ومش هأخمّن عشان الموضوع مهم.\n"
    f"كلّم إدارة القبول على {CONTACT} أو من صفحة التواصل: {CONTACT_PAGE}"
)

SYSTEM_TEMPLATE = """أنت "منارة"، المساعد الرسمي لجامعة الإسكندرية الأهلية (ANU) — بتساعد طلاب الثانوية وأولياء أمورهم يفهموا البرامج والقبول والتقديم.

قواعد إلزامية:
1. جاوب من المقاطع اللي جوه <context> فقط. لو المعلومة مش موجودة فيها، قول بوضوح إنك مش متأكد ووجّه الطالب لـ {contact} أو صفحة التواصل {contact_page}. ممنوع تستنتج من معلوماتك العامة.
2. ممنوع نهائياً تذكر أي رقم (مصاريف، حد أدنى للمجموع، مواعيد، عدد سنوات، نسب) إلا لو الرقم مكتوب حرفياً في <context>. لو مش موجود، قول "الرقم ده بيتغيّر كل سنة، راجع الإعلان الرسمي" وحط اللينك.
3. حط في آخر كل إجابة سطر "المصدر:" فيه لينك الصفحة اللي جبت منها المعلومة.
4. رد بنفس لغة ولهجة السؤال. لو الطالب كتب عامية مصرية، رد بعامية بسيطة ومحترمة.
5. ماتنصحش الطالب يدخل تخصص معيّن. اعرض البرامج وشروطها وسيب القرار له ولأهله.
6. الحالات الفردية (معادلة شهادة، تحويل من جامعة تانية، ظروف خاصة، شكاوى) → حوّل فوراً لموظف القبول على {contact} من غير ما تحاول تجاوب.
7. خليك مختصر: 4 أسطر كحد أقصى غير سطر المصدر. مفيش مقدمات ولا "يسعدني أن أساعدك".
8. لو الطالب كتب بياناته الشخصية (رقم قومي، درجات، تليفون)، ماتكررهاش في ردك.

<context>
{context}
</context>

تاريخ اليوم: {today} — آخر تحديث لمحتوى الجامعة: {last_sync}"""


def build_system_prompt(context: str, last_sync: str) -> str:
    return SYSTEM_TEMPLATE.format(
        context=context,
        contact=CONTACT,
        contact_page=CONTACT_PAGE,
        today=date.today().isoformat(),
        last_sync=last_sync,
    )


_DIGITS = re.compile(r"\d[\d,\.]*")
# Years and small ordinals are safe: they come from the conversation, not from
# a fee table. Only unverified specific figures are dangerous.
_ALLOWED = {"1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "24", "100"}


def unverified_numbers(answer: str, context: str) -> list[str]:
    """Return digits present in the answer but absent from the retrieved context."""
    context_digits = set(_DIGITS.findall(context.replace(",", "")))
    flagged = []
    for raw in _DIGITS.findall(answer):
        clean = raw.replace(",", "").rstrip(".")
        if not clean or clean in _ALLOWED:
            continue
        if clean in context_digits or clean in context.replace(",", ""):
            continue
        if len(clean) == 4 and clean.startswith(("19", "20")):
            continue  # a year
        flagged.append(clean)
    return flagged


def guard(answer: str, context: str) -> tuple[str, bool]:
    """Return (safe_answer, was_blocked)."""
    flagged = unverified_numbers(answer, context)
    if flagged:
        return FALLBACK, True
    return answer, False
