import pytest

from app.services.reply_check_service import check_reply


def promises(draft, knowledge=(), **turn):
    evidence = dict(profile={}, history=[], customer_message="")
    findings = check_reply(draft, knowledge=knowledge, **(evidence | turn))
    return [f for f in findings if f["category"] == "promise"]


@pytest.mark.parametrize(("draft", "subtype", "safe"), [
    ("We guarantee you will pass.", "guarantee", "We cannot guarantee you will pass."),
    ("It is 100% certain.", "guarantee", "This bag is 100% cotton."),
    ("Keputusan dijamin.", "guarantee", "Keputusan tidak dijamin."),
    ("我们保证通过。", "guarantee", "我们不能保证通过。"),
    ("You'll receive a full refund.", "refund", "How do I request a full refund?"),
    ("Kami beri bayaran balik penuh.", "refund", "Anda boleh memohon bayaran balik penuh."),
    ("我们会全额退款。", "refund", "您可以申请全额退款。"),
    ("You get a discount.", "discount", "Would you like me to check the discount?"),
    ("一定可以打八折。", "discount", "这件商品可以打八折吗？"),
    ("Delivery is free.", "free_item", "Feel free to call the desk."),
    ("Krim ini percuma.", "free_item", "Adakah krim ini percuma?"),
    ("送货免费。", "free_item", "送货不免费。"),
    ("Rider pasti sampai esok.", "timing", "Rider tak pasti sampai esok."),
    ("Rawatan ini dijamin akan sembuh.", "medical", "Doktor tidak boleh menjamin anda akan sembuh."),
    ("这次治疗一定能治好你。", "medical", "这次治疗不一定能治好你。"),
    ("你一定会胜诉。", "legal", "不能保证你会胜诉。"),
    ("Loan awak confirm approved.", "financial", "Loan awak confirm approved?"),
], ids=["guarantee-en", "certainty", "guarantee-ms", "guarantee-zh", "refund-en", "refund-ms",
        "refund-zh", "discount-en", "discount-zh", "free-en", "free-ms", "free-zh", "timing-ms",
        "medical-ms", "medical-zh", "legal-zh", "financial-mixed"])
def test_asserted_promise_and_its_safe_counterpart(draft, subtype, safe):
    assert promises(draft, history=[{"role": "user", "content": draft}], profile={"note": draft},
                    customer_message=draft) == [{"category": "promise", "subtype": subtype}]
    assert not promises(safe)
    assert not promises(draft, knowledge=[{"content": draft}])


@pytest.mark.parametrize(("offer", "supported", "unsupported", "subtype"), [
    ("Delivery is free on orders over RM100.", "Delivery is free on orders over RM100.",
     "Delivery is free.", "free_item"),
    ("The sample is free.", "The sample is free.", "The replacement is free.", "free_item"),
    ("We offer a full refund for unopened items.", "We offer a full refund for unopened items.",
     "We offer a full refund for used items.", "refund"),
    ("Delivery is not guaranteed.", "Delivery is not guaranteed.", "Delivery is guaranteed.", "timing"),
    ("We cannot guarantee a cure.", "We cannot guarantee a cure.",
     "We cannot guarantee a cure, but your consultation is free.", "free_item"),
    ("上门安装仅限新客免费。", "上门安装仅限新客免费。", "上门安装免费。", "free_item"),
], ids=["threshold", "different-item", "refund-condition", "negated-policy", "separate-clause", "zh-condition"])
def test_support_must_cover_the_actual_offer(offer, supported, unsupported, subtype):
    assert promises(unsupported, [offer]) == [{"category": "promise", "subtype": subtype}]
    assert not promises(supported, [offer])


@pytest.mark.parametrize(("draft", "subtype", "safe"), [
    ("We promise delivery by tomorrow.", "timing", "We sell gluten-free bread."),
    ("Saya menjamin anda akan menang di mahkamah.", "legal", "Sila pastikan alamat anda betul."),
    ("Kami menjamin pinjaman akan diluluskan.", "financial", "The next available slot is free of bookings."),
    ("You get 25% off.", "discount", "This costs 100% of the published price."),
], ids=["timing-en", "legal-ms", "financial-ms", "discount-en"])
def test_explicit_commitments_and_non_promotional_wording(draft, subtype, safe):
    assert promises(draft) == [{"category": "promise", "subtype": subtype}]
    assert not promises(safe)


def test_following_eligibility_sentence_applies_to_the_published_offer():
    policy = "Delivery is free. Only for first-time customers."
    assert promises("Delivery is free.", [policy]) == [{"category": "promise", "subtype": "free_item"}]
    assert not promises(policy, [policy])


def test_full_refund_policy_can_be_quoted_with_its_item_and_condition():
    policy = "Refund policy: full refund for unopened items."
    assert promises("You get a full refund for opened items.", [policy])
    assert not promises("You get a full refund for unopened items.", [policy])


@pytest.mark.parametrize(("policy", "quote", "unsupported"), [
    ("Shipping is free for orders over RM100.", "Our policy says: delivery is free for orders above RM100.",
     "Our policy says: delivery is free for orders above RM10."),
    ("We guarantee delivery by noon.", 'The published policy says: "We guarantee delivery by noon."',
     'The published policy says: "We guarantee delivery by dawn."'),
])
def test_attributed_quotations_preserve_offer_terms(policy, quote, unsupported):
    assert not promises(quote, [policy])
    assert promises(unsupported, [policy])
