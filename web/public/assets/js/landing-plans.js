(function(){
  'use strict';
  const catalog=window.SubscriptionPlanCatalog&&window.SubscriptionPlanCatalog.plans;
  if(!Array.isArray(catalog)) return;
  const money=function(sen){return 'RM '+(Number(sen)/100).toFixed(2)};
  const update=function(months){
    document.querySelectorAll('[data-plan-code]').forEach(function(card){
      const code=card.getAttribute('data-plan-code');
      if(code==='free') return;
      const plan=catalog.find(function(item){return item.code===code});
      const term=plan&&Array.isArray(plan.billing_terms)&&plan.billing_terms.find(function(item){return Number(item.months)===months});
      if(!term) return;
      const price=card.querySelector('[data-plan-price]');
      const total=card.querySelector('[data-plan-total]');
      const termValue=card.querySelector('[data-plan-term]');
      const discount=card.querySelector('[data-plan-discount]');
      if(price) price.textContent=money(term.monthly_equivalent_sen);
      if(total) total.textContent=money(term.amount_sen);
      if(termValue) termValue.textContent=String(term.months);
      if(discount) discount.textContent=String(term.discount_percent)+'%';
    });
  };
  document.querySelectorAll('[data-landing-term]').forEach(function(button){
    button.addEventListener('click',function(){
      const months=Number(button.getAttribute('data-landing-term'));
      if([1,3,6,12].indexOf(months)===-1) return;
      document.querySelectorAll('[data-landing-term]').forEach(function(option){
        const selected=Number(option.getAttribute('data-landing-term'))===months;
        option.classList.toggle('is-selected',selected);
        option.setAttribute('aria-checked',selected?'true':'false');
      });
      update(months);
    });
  });
  update(1);
})();
