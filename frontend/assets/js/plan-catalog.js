(function () {
    "use strict";

    var plans = [
        {
            code: "free",
            name: "Free",
            description: "Basic plan for trying the chatbot platform.",
            price: "0",
            currency: "MYR",
            billing_interval: "monthly",
            chatbot_limit: 1,
            team_member_limit: 1,
            channel_limit: 1,
            knowledge_file_limit: 3,
            knowledge_storage_limit_bytes: 52428800,
            model_access_label: "DeepSeek Only",
            included_ai_credit_micro_myr: 1000000,
            trial_only: true,
            featured: false,
            feature_flags: {
                single_website_scraping: false,
                batch_website_scraping: false,
                ai_assisted_menu_generation: false,
                ai_generated_reports: false,
                crm_lead_assignment: false,
                knowledge_refinement: false
            }
        },
        {
            code: "essential",
            name: "Essential",
            description: "Essential plan - 1 chatbot, 1 channel, 5 knowledge files, 50 MB storage",
            price: "39",
            currency: "MYR",
            billing_interval: "monthly",
            chatbot_limit: 1,
            team_member_limit: 1,
            channel_limit: 1,
            knowledge_file_limit: 5,
            knowledge_storage_limit_bytes: 52428800,
            model_access_label: "Economy Model Tier",
            included_ai_credit_micro_myr: 5000000,
            trial_only: false,
            featured: false,
            feature_flags: {
                single_website_scraping: false,
                batch_website_scraping: false,
                ai_assisted_menu_generation: false,
                ai_generated_reports: false,
                crm_lead_assignment: false,
                knowledge_refinement: false
            }
        },
        {
            code: "advanced",
            name: "Advanced",
            description: "Advanced plan - 2 chatbots, 2 channels, 25 knowledge files, 250 MB storage",
            price: "89",
            currency: "MYR",
            billing_interval: "monthly",
            chatbot_limit: 2,
            team_member_limit: 3,
            channel_limit: 2,
            knowledge_file_limit: 25,
            knowledge_storage_limit_bytes: 262144000,
            model_access_label: "Standard Model Tier",
            included_ai_credit_micro_myr: 20000000,
            trial_only: false,
            featured: true,
            feature_flags: {
                single_website_scraping: true,
                batch_website_scraping: false,
                ai_assisted_menu_generation: true,
                ai_generated_reports: false,
                crm_lead_assignment: true,
                knowledge_refinement: false
            }
        },
        {
            code: "pro",
            name: "Pro",
            description: "Premium plan for teams that need the highest published limits and full feature access.",
            price: "169",
            currency: "MYR",
            billing_interval: "monthly",
            chatbot_limit: 3,
            team_member_limit: 5,
            channel_limit: 2,
            knowledge_file_limit: 75,
            knowledge_storage_limit_bytes: 1073741824,
            model_access_label: "Premium Model Tier",
            included_ai_credit_micro_myr: 60000000,
            trial_only: false,
            featured: false,
            feature_flags: {
                single_website_scraping: true,
                batch_website_scraping: true,
                ai_assisted_menu_generation: true,
                ai_generated_reports: true,
                crm_lead_assignment: true,
                knowledge_refinement: true
            }
        }
    ];

    window.SubscriptionPlanCatalog = Object.freeze({
        plans: Object.freeze(plans.map(function (plan) {
            return Object.freeze(plan);
        }))
    });
})();
