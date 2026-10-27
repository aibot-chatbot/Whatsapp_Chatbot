(function(){
  'use strict';

  const EN_OVERRIDES={
    "Berapakah harga chatbot AI WhatsApp untuk bisnes di Malaysia?":"How much does a WhatsApp AI chatbot cost for a Malaysian business?",
    "Omnexa menggabungkan chatbot AI dan analisis GEO untuk perniagaan di Malaysia. Pelan berbayar bermula daripada nilai bulanan RM 89 dengan tempoh prabayar 12 bulan. Setiap akaun baharu bermula dengan percubaan percuma 7 hari, tanpa kad.":"Omnexa combines an AI chatbot and GEO analysis for Malaysian businesses. Paid plans start from RM 89 per month equivalent on a 12-month prepaid term. Every new account starts with a free 7-day trial, with no card required."
  };

  const ZH={
    "Primary":"主导航",
    "Features":"功能",
    "Integrations":"集成",
    "Pricing":"价格",
    "Sign in":"登录",
    "Start free trial":"开始免费试用",
    "Built for Malaysian businesses":"专为马来西亚企业打造",
    "WhatsApp AI chatbot for Malaysian businesses":"面向马来西亚企业的 WhatsApp AI 聊天机器人",
    "Boost Your businesses":"助力您的业务增长",
    "Scale Your Business on Complete Autopilot":"让您的业务实现全自动规模化增长",
    "Scale Your Business on Autopilot":"让您的业务自动扩展",
    "Omnexa answers your customers on WhatsApp, Telegram and your website chat, using your own PDFs and web pages. Every conversation is saved to a built-in CRM, and your team can read the history and reply from the same inbox.":"Omnexa 使用您自己的 PDF 和网页内容，在 WhatsApp、Telegram 与网站聊天中回复客户。每段对话都会保存到内置 CRM，团队可在同一个收件箱查看记录并回复。",
    "Omnexa combines WhatsApp, Telegram and AI customer agents, automated workflows, SEO and GEO ranking, and website hosting in one unified platform.":"Omnexa 将 WhatsApp、Telegram、AI 客服代理、自动化工作流、SEO 与 GEO 排名以及网站托管整合到一个统一平台中。",
    "7 days free, no card required":"免费 7 天，无需信用卡",
    "Website chat":"网站聊天",
    "Soon":"即将推出",
    "How it works":"运作方式",
    "Set up your WhatsApp AI chatbot in three steps":"只需三步设置 WhatsApp AI 聊天机器人",
    "01 — CONNECT":"01 — 连接",
    "Connect your channels":"连接您的渠道",
    "Link WhatsApp through the official Cloud API or a Wasender session, add a Telegram bot token, or switch on the website chat.":"通过官方 Cloud API 或 Wasender 会话连接 WhatsApp，添加 Telegram 机器人令牌，或启用网站聊天。",
    "02 — TEACH":"02 — 训练",
    "Add your knowledge":"添加您的知识内容",
    "Upload PDFs and add your website pages. The chatbot answers from this content.":"上传 PDF 并添加网站页面，聊天机器人会依据这些内容回答。",
    "03 — GO LIVE":"03 — 上线",
    "Answer, track and follow up":"回复、追踪与跟进",
    "Replies land in one inbox and on each customer's CRM record. Send broadcasts by tag, now or scheduled.":"回复会进入统一收件箱及每位客户的 CRM 记录。可按标签立即或定时发送广播。",
    "Auto reply, CRM and broadcasts in one place":"自动回复、CRM 与广播集中一处",
    "Broadcast to WhatsApp and Telegram from one composer":"从同一个编辑器向 WhatsApp 和 Telegram 发送广播",
    "Write once, pick an audience by CRM tag, and send now or schedule it. No copy-paste between apps.":"内容只需撰写一次，按 CRM 标签选择受众，然后立即或定时发送，无需在应用之间复制粘贴。",
    "Illustration. Product screenshots coming.":"示意图。产品截图即将推出。",
    "WhatsApp auto reply from your own documents":"依据自有文档自动回复 WhatsApp",
    "Upload PDFs and add your website pages so replies draw on your real content, not general knowledge.":"上传 PDF 并添加网站页面，让回复依据您的真实内容，而不是通用知识。",
    "A built-in CRM that remembers every customer":"记住每位客户的内置 CRM",
    "Every conversation writes back to a CRM record with tags, status and staff assignment.":"每段对话都会写入 CRM 记录，并包含标签、状态和员工分配。",
    "Built for":"适用于",
    "Answer enquiries and collect bookings in the chat":"在聊天中回复咨询并收集预约",
    "Agencies":"代理机构",
    "Run broadcasts for several client brands from separate workspaces, each with its own channels, contacts and knowledge base.":"通过独立工作区为多个客户品牌运行广播，每个工作区都有自己的渠道、联系人和知识库。",
    "Online stores":"网店",
    "Send order updates and restock alerts to WhatsApp, then let the bot answer follow-up questions from your product documentation.":"通过 WhatsApp 发送订单更新和补货提醒，再让机器人依据产品文档回答后续问题。",
    "Service businesses":"服务型企业",
    "Let the chatbot collect booking requests on WhatsApp, Telegram or your website chat. Your staff confirm each one, and the list downloads as a CSV file.":"让聊天机器人在 WhatsApp、Telegram 或网站聊天中收集预约请求。员工逐一确认后，可将列表下载为 CSV 文件。",
    "Support teams":"客服团队",
    "Answer repeat questions from your own help articles, and let your staff pick up the rest with the full conversation history.":"依据自有帮助文章回答重复问题，其余问题由员工结合完整对话记录继续处理。",
    "WhatsApp, Telegram and website chat in one inbox":"WhatsApp、Telegram 与网站聊天集中在一个收件箱",
    "The official WhatsApp Business API. Connect your own number through Meta embedded signup.":"官方 WhatsApp Business API。通过 Meta 嵌入式注册连接您自己的号码。",
    "Add a bot token and start publishing to channels and groups.":"添加机器人令牌，即可向频道和群组发布内容。",
    "Route WhatsApp traffic through a Wasender session.":"通过 Wasender 会话路由 WhatsApp 流量。",
    "A chat widget for your own website and a shareable chat link are included as well, and neither uses a channel slot.":"方案还包含网站聊天组件和可分享的聊天链接，两者都不占用渠道名额。",
    "In development":"开发中",
    "Instagram, Facebook, X and LinkedIn are not available yet. They are on the roadmap and are not included in any plan today.":"Instagram、Facebook、X 和 LinkedIn 尚未开放，已列入路线图，目前不包含在任何方案中。",
    "Under the hood":"核心功能",
    "Knowledge base, automation and one inbox":"知识库、自动化与统一收件箱",
    "Knowledge base":"知识库",
    "Upload documents and scrape pages; replies cite what you gave it.":"上传文档并抓取网页；回复会引用您提供的内容。",
    "Automation":"自动化",
    "Route conversations through decision flows instead of manual triage.":"通过决策流程路由对话，无需人工分流。",
    "Broadcast":"广播",
    "One message fans out to a segmented audience.":"一条消息即可发送给细分受众。",
    "Unified inbox":"统一收件箱",
    "Every channel lands in the same conversation view.":"所有渠道都汇集到同一个对话视图。",
    "Where things stand":"当前进展",
    "What Omnexa does today":"Omnexa 目前可以做什么",
    "Channels live — WhatsApp Cloud API, Telegram, Wasender":"已上线渠道 — WhatsApp Cloud API、Telegram、Wasender",
    "In development — Instagram, Facebook, X, LinkedIn":"开发中 — Instagram、Facebook、X、LinkedIn",
    "Grounded":"有据可依",
    "Replies cite documents you upload":"回复会引用您上传的文档",
    "One inbox":"一个收件箱",
    "Every channel in the same conversation view":"所有渠道都在同一个对话视图",
    "We built Omnexa because running broadcasts across WhatsApp and Telegram meant three tools and a spreadsheet. It should be one composer. If something is missing for your team, tell us and we will build it.":"我们打造 Omnexa，是因为过去要在 WhatsApp 和 Telegram 运行广播，需要三种工具和一份电子表格。它本应由一个编辑器完成。如果团队缺少某项功能，请告诉我们，我们会把它做出来。",
    "— Founder, Omnexa":"— Omnexa 创始人",
    "Before you sign up":"注册前须知",
    "A Malaysian company.":"马来西亚公司。",
    "Omnexa is operated by Meta Realty Sdn Bhd (SSM 202201040486), Puchong, Selangor.":"Omnexa 由位于雪兰莪蒲种的 Meta Realty Sdn Bhd（SSM 202201040486）运营。",
    "Prices in Ringgit, shown in full.":"价格以马来西亚令吉完整列明。",
    "Every plan and its limits are listed below. Starting the 7-day trial needs no card.":"所有方案及其限制均列于下方。开始 7 天试用无需信用卡。",
    "The official WhatsApp API.":"官方 WhatsApp API。",
    "Connect through Meta's WhatsApp Cloud API, or use a Wasender session if you prefer.":"通过 Meta 的 WhatsApp Cloud API 连接，或按需要使用 Wasender 会话。",
    "Your team stays in control.":"团队始终掌控全局。",
    "Staff can read and reply to any conversation from the same inbox.":"员工可在同一个收件箱查看并回复任何对话。",
    "Your customers' data.":"您的客户数据。",
    "We do not sell personal data to advertisers. Read our":"我们不会将个人数据出售给广告商。请阅读我们的",
    "privacy policy":"隐私政策",
    ", also in":"，另有",
    "Bahasa Malaysia":"马来西亚语版本",
    ".":"。",
    "Chatbot + GEO pricing in Malaysian Ringgit":"以马来西亚令吉计价的聊天机器人 + GEO 方案",
    "Paid plans bundle Chatbot and GEO.":"付费方案同时包含聊天机器人和 GEO。",
    "Choose a 1, 3, 6 or 12-month term and pay the full term upfront. AI credit and GEO allowances still reset every month; one provider check means one combined keyword topic sent to one AI-search platform. Every new account starts with a 7-day Free trial, with no card required; usage beyond the included AI credit is billed separately.":"选择 1、3、6 或 12 个月期限，并一次性支付整个期限。AI 信用额和 GEO 配额仍按月重置；一次提供商检查表示向一个 AI 搜索平台发送一个合并关键词主题。每个新账户都可享受 7 天 Free 试用，无需信用卡；超出所含 AI 信用额的用量将另行计费。",
    "Choose a billing term":"选择计费期限",
    "Subscription term":"订阅期限",
    "1 month":"1 个月",
    "3 months":"3 个月",
    "6 months":"6 个月",
    "12 months":"12 个月",
    "/ month equivalent":"/ 月均价",
    "charged upfront for a":"一次性支付",
    "-month term · Save":"个月期限 · 节省",
    "Prices are monthly, in Malaysian Ringgit.":"价格按月计算，并以马来西亚令吉计价。",
    "Every new account starts with a 7-day free trial of the Free plan, with no card required. To keep AI replies on after the trial, choose a paid plan. Every plan includes an AI credit allowance, and usage beyond the allowance is billed separately. Paid plans also include a separate monthly GEO allowance; one provider check means one combined keyword topic sent to one AI-search platform.":"每个新账户都会获得 Free 方案的 7 天免费试用，无需信用卡。试用结束后如需继续使用 AI 回复，请选择付费方案。每个方案都包含 AI 信用额度，超出额度的用量将另行计费。付费方案还包含独立的每月 GEO 额度；一次提供商检查表示向一个 AI 搜索平台发送一个合并关键词主题。",
    "7-day free trial only":"仅限 7 天免费试用",
    "1 bot":"1 个机器人",
    "1 channel":"1 个渠道",
    "1 seat":"1 个席位",
    "3 knowledge files, 50 MB":"3 个知识文件，50 MB",
    "RM 1 AI credit for the trial":"试用期 RM 1 AI 信用额",
    "AI models: 1 entry model":"AI 模型：1 个入门模型",
    "Chat booking requests":"聊天预约请求",
    "Start 7-day trial":"开始 7 天试用",
    "5 knowledge files, 50 MB":"5 个知识文件，50 MB",
    "RM 5 AI credit monthly":"每月 RM 5 AI 信用额",
    "AI models: GPT-6 Luna, Gemini 3.8 Flash":"AI 模型：GPT-6 Luna、Gemini 3.8 Flash",
    "GEO: 10 provider checks monthly":"GEO：每月 10 次提供商检查",
    "5 live GEO APIs":"5 个实时 GEO API",
    "AI-derived bot persona":"AI 派生的机器人角色",
    "Conversation memory":"对话记忆",
    "2 bots":"2 个机器人",
    "2 channels":"2 个渠道",
    "3 seats":"3 个席位",
    "25 knowledge files, 250 MB":"25 个知识文件，250 MB",
    "RM 20 AI credit monthly":"每月 RM 20 AI 信用额",
    "AI models: GPT-6 Luna, Gemini 3.8 Flash, Claude Haiku 4.5":"AI 模型：GPT-6 Luna、Gemini 3.8 Flash、Claude Haiku 4.5",
    "GEO: 40 provider checks monthly":"GEO：每月 40 次提供商检查",
    "Up to 10 keywords per GEO analysis":"每次 GEO 分析最多 10 个关键词",
    "CRM lead assignment":"CRM 潜在客户分配",
    "Single website scraping":"单个网站抓取",
    "AI-assisted menu generation":"AI 辅助菜单生成",
    "Guided knowledge ingestion":"引导式知识导入",
    "3 bots":"3 个机器人",
    "4 channels":"4 个渠道",
    "5 seats":"5 个席位",
    "75 knowledge files, 1 GB":"75 个知识文件，1 GB",
    "RM 60 AI credit monthly":"每月 RM 60 AI 信用额",
    "AI models: GPT-6.1 Sol, Claude Sonnet 5.5, Gemini 3.1 Pro":"AI 模型：GPT-6.1 Sol、Claude Sonnet 5.5、Gemini 3.1 Pro",
    "GEO: 120 provider checks monthly":"GEO：每月 120 次提供商检查",
    "AI-generated reports":"AI 生成报告",
    "Automation workflows":"自动化工作流程",
    "Knowledge refinement Q&A":"知识优化问答",
    "Batch website scraping":"批量网站抓取",
    "Availability booking":"可用时段预约",
    "Questions":"常见问题",
    "WhatsApp AI chatbot questions, answered":"WhatsApp AI 聊天机器人常见问题解答",
    "What is Omnexa?":"什么是 Omnexa？",
    "Omnexa combines an AI chatbot and GEO analysis for small and medium businesses in Malaysia. Paid plans start from RM 89 per month equivalent on a 12-month prepaid term.":"Omnexa 为马来西亚中小企业结合 AI 聊天机器人和 GEO 分析。12 个月预付期限的付费方案月均价低至 RM 89。",
    "How much does a WhatsApp AI chatbot cost with Omnexa?":"使用 Omnexa 的 WhatsApp AI 聊天机器人多少钱？",
    "For a one-month term, Essential costs RM 133.50, Advanced RM 283.50 and Pro RM 561.00. Lower monthly equivalents are available for 3, 6 and 12-month prepaid terms. Every new account starts with a 7-day Free trial, with no card required.":"一个月期限的价格为 Essential RM 133.50、Advanced RM 283.50、Pro RM 561.00。选择 3、6 或 12 个月预付期限可享更低月均价。每个新账户都可享受 7 天 Free 试用，无需信用卡。",
    "How do I add an AI chatbot to my business WhatsApp?":"如何为企业 WhatsApp 添加 AI 聊天机器人？",
    "Sign up, then connect your number through the official WhatsApp Cloud API or a Wasender session. Upload PDFs or add your website pages, and Omnexa starts answering customers from that content and saving each conversation to its CRM.":"注册后，通过官方 WhatsApp Cloud API 或 Wasender 会话连接号码。上传 PDF 或添加网站页面后，Omnexa 就会依据这些内容回复客户，并将每段对话保存到 CRM。",
    "Where does the chatbot get its answers?":"聊天机器人的答案来自哪里？",
    "From the documents you upload and the website pages you add, rather than general knowledge, so replies reflect what your business has actually published.":"答案来自您上传的文档和添加的网站页面，而不是通用知识，因此回复会反映企业实际发布的内容。",
    "Can my staff reply instead of the bot?":"员工可以代替机器人回复吗？",
    "Yes. Every conversation lands in one inbox next to its CRM record, with tags, status and staff assignment, so your team can read the full history and reply to the customer directly.":"可以。每段对话都会进入统一收件箱，并显示对应的 CRM 记录、标签、状态和员工分配，团队可查看完整记录并直接回复客户。",
    "Can customers book appointments through the chat?":"客户可以通过聊天预约吗？",
    "Yes. Once you switch bookings on for a chatbot, it collects booking requests in the chat. Your staff confirm each request, and the full list downloads as a CSV file.":"可以。为聊天机器人启用预约后，它会在聊天中收集预约请求。员工确认每项请求后，可将完整列表下载为 CSV 文件。",
    "Which channels does Omnexa support?":"Omnexa 支持哪些渠道？",
    "WhatsApp (through the official Cloud API or a Wasender session), Telegram and a chat widget for your own website are live today. Instagram, Facebook, X and LinkedIn are in development and are not included in any plan yet.":"目前已支持 WhatsApp（通过官方 Cloud API 或 Wasender 会话）、Telegram 以及网站聊天组件。Instagram、Facebook、X 和 LinkedIn 仍在开发中，尚未包含在任何方案内。",
    "Do I need a Meta Business account?":"需要 Meta Business 账户吗？",
    "Yes, for the WhatsApp Cloud API. Telegram needs only a bot token, which takes about a minute to create, and the website chat needs no outside account.":"使用 WhatsApp Cloud API 需要。Telegram 只需机器人令牌，约一分钟即可创建；网站聊天则无需外部账户。",
    "Which AI models does Omnexa use?":"Omnexa 使用哪些 AI 模型？",
    "Essential includes GPT-6 Luna and Gemini 3.8 Flash. Advanced adds Claude Haiku 4.5. Pro includes GPT-6.1 Sol, Claude Sonnet 5.5 and Gemini 3.1 Pro. The 7-day free trial uses one entry model. On paid plans you choose which included model each chatbot uses.":"Essential 包含 GPT-6 Luna 和 Gemini 3.8 Flash；Advanced 增加 Claude Haiku 4.5；Pro 包含 GPT-6.1 Sol、Claude Sonnet 5.5 和 Gemini 3.1 Pro。7 天免费试用使用一个入门模型。付费方案可为每个聊天机器人选择所含模型。",
    "Berapakah harga chatbot AI WhatsApp untuk bisnes di Malaysia?":"马来西亚企业使用 WhatsApp AI 聊天机器人多少钱？",
    "Omnexa menggabungkan chatbot AI dan analisis GEO untuk perniagaan di Malaysia. Pelan berbayar bermula daripada nilai bulanan RM 89 dengan tempoh prabayar 12 bulan. Setiap akaun baharu bermula dengan percubaan percuma 7 hari, tanpa kad.":"Omnexa 为马来西亚企业结合 AI 聊天机器人和 GEO 分析。12 个月预付期限的付费方案月均价低至 RM 89。每个新账户均享有 7 天免费试用，无需信用卡。",
    "Put an AI chatbot on your WhatsApp today":"立即为 WhatsApp 添加 AI 聊天机器人",
    "Connect WhatsApp, Telegram or your website, upload your documents, and let Omnexa answer your customers.":"连接 WhatsApp、Telegram 或您的网站，上传文档，让 Omnexa 为您回复客户。",
    "WhatsApp AI chatbot, CRM and broadcasts for Malaysian businesses.":"面向马来西亚企业的 WhatsApp AI 聊天机器人、CRM 与广播。",
    "Product":"产品",
    "Company":"公司",
    "About":"关于我们",
    "Contact":"联系我们",
    "Resources":"资源",
    "Legal":"法律信息",
    "Privacy":"隐私",
    "Terms":"条款",
    "Omnexa. Operated by Meta Realty Sdn Bhd (SSM 202201040486), Malaysia.":"Omnexa 由马来西亚 Meta Realty Sdn Bhd（SSM 202201040486）运营。",
    "Go to your bots":"前往您的机器人",
    "View plans":"查看方案",
    "Language":"语言",
    "Switch to light mode":"切换到浅色模式",
    "Switch to dark mode":"切换到深色模式",
    "Omnexa product demonstration showing an AI customer agent conversation":"Omnexa 产品演示，展示 AI 客服代理对话",
    "A single message splitting through a prism into separate channel streams":"一条消息穿过棱镜，分流到不同渠道",
    "Document pages folding into a reply bubble, linked by glowing filaments":"文档页面折叠成回复气泡，并由发光线条连接",
    "A contact card orbited by tags and status rings":"联系人卡片周围环绕着标签和状态环",
    "The robot routing messages into three client workspaces":"机器人将消息路由到三个客户工作区",
    "The robot handing a parcel toward an order-update message":"机器人把包裹递向订单更新消息",
    "The robot placing a checkmark on a calendar slot":"机器人在日历时段上添加勾选标记",
    "The robot lifting a document sheet into a reply bubble":"机器人将文档页送入回复气泡",
    "The robot holding a glowing chat bubble":"机器人手持发光聊天气泡",
    "The robot releasing a paper-plane of light":"机器人放出一架光影纸飞机",
    "The robot beside a relay tower emitting signal rings":"机器人站在发射信号环的中继塔旁",
    "A lattice of document shards forming an index sphere":"文档碎片构成索引球体",
    "A node graph with one path lit brighter":"节点图中有一条路径更加明亮",
    "A core pulsing outward into many points of light":"核心向外脉动并扩散成多个光点",
    "Separate streams converging into one channel":"多条独立信息流汇聚到一个渠道",
    "Scroll to explore":"向下滚动探索",
    "AI customer agent":"AI 客服代理",
    "Every customer answered in seconds":"每位客户，数秒内得到回复",
    "Replies on WhatsApp, Telegram and your website chat, day and night, using your own PDFs and web pages.":"全天候在 WhatsApp、Telegram 和您的网站聊天中回复客户，答案来自您自己的 PDF 和网页。",
    "CRM and analytics":"CRM 与分析",
    "Every chat becomes a lead you can see":"每段对话都成为清晰可见的潜在客户",
    "Contacts, conversations and bookings land in one built-in CRM, with reports on what customers ask.":"联系人、对话和预约都汇集到内置 CRM，并附有客户提问的分析报告。",
    "Automation workflow":"自动化工作流",
    "Follow-ups that run themselves":"跟进工作自动完成",
    "Route new leads to the right teammate and trigger the next step automatically.":"将新的潜在客户分配给合适的同事，并自动触发下一步。",
    "See it run":"实际运行",
    "One enquiry, a complete workflow":"一个询问，一套完整流程",
    "Watch an enquiry move from the WhatsApp inbox to a routed workflow and into GEO insight.":"观看一个询问如何从 WhatsApp 收件箱进入分派好的工作流，再到 GEO 洞察。",
    "Product demo with illustrative data.":"产品演示，数据仅作示意。"
  };

  const MS={
    "Primary":"Navigasi utama",
    "Features":"Ciri",
    "Integrations":"Integrasi",
    "Pricing":"Harga",
    "Sign in":"Log masuk",
    "Start free trial":"Mulakan percubaan percuma",
    "Built for Malaysian businesses":"Dibina untuk perniagaan Malaysia",
    "WhatsApp AI chatbot for Malaysian businesses":"Chatbot AI WhatsApp untuk perniagaan Malaysia",
    "Boost Your businesses":"Tingkatkan perniagaan anda",
    "Scale Your Business on Complete Autopilot":"Skalakan perniagaan anda secara automatik sepenuhnya",
    "Scale Your Business on Autopilot":"Skalakan perniagaan anda secara automatik",
    "Omnexa answers your customers on WhatsApp, Telegram and your website chat, using your own PDFs and web pages. Every conversation is saved to a built-in CRM, and your team can read the history and reply from the same inbox.":"Omnexa menjawab pelanggan anda melalui WhatsApp, Telegram dan sembang laman web menggunakan PDF serta halaman web anda sendiri. Setiap perbualan disimpan dalam CRM terbina dalam, dan pasukan anda boleh membaca sejarah serta membalas dari peti masuk yang sama.",
    "Omnexa combines WhatsApp, Telegram and AI customer agents, automated workflows, SEO and GEO ranking, and website hosting in one unified platform.":"Omnexa menggabungkan WhatsApp, Telegram dan ejen pelanggan AI, aliran kerja automatik, kedudukan SEO dan GEO serta pengehosan laman web dalam satu platform bersepadu.",
    "7 days free, no card required":"Percuma 7 hari, tanpa kad",
    "Website chat":"Sembang laman web",
    "Soon":"Akan datang",
    "How it works":"Cara ia berfungsi",
    "Set up your WhatsApp AI chatbot in three steps":"Sediakan chatbot AI WhatsApp anda dalam tiga langkah",
    "01 — CONNECT":"01 — SAMBUNG",
    "Connect your channels":"Sambungkan saluran anda",
    "Link WhatsApp through the official Cloud API or a Wasender session, add a Telegram bot token, or switch on the website chat.":"Pautkan WhatsApp melalui Cloud API rasmi atau sesi Wasender, tambah token bot Telegram, atau aktifkan sembang laman web.",
    "02 — TEACH":"02 — AJAR",
    "Add your knowledge":"Tambahkan pengetahuan anda",
    "Upload PDFs and add your website pages. The chatbot answers from this content.":"Muat naik PDF dan tambahkan halaman laman web anda. Chatbot menjawab berdasarkan kandungan ini.",
    "03 — GO LIVE":"03 — SIAR LANGSUNG",
    "Answer, track and follow up":"Jawab, jejak dan susuli",
    "Replies land in one inbox and on each customer's CRM record. Send broadcasts by tag, now or scheduled.":"Balasan masuk ke satu peti masuk dan rekod CRM setiap pelanggan. Hantar siaran mengikut tag, sekarang atau berjadual.",
    "Auto reply, CRM and broadcasts in one place":"Balasan automatik, CRM dan siaran di satu tempat",
    "Broadcast to WhatsApp and Telegram from one composer":"Siar ke WhatsApp dan Telegram dari satu penyunting",
    "Write once, pick an audience by CRM tag, and send now or schedule it. No copy-paste between apps.":"Tulis sekali, pilih khalayak mengikut tag CRM, kemudian hantar sekarang atau jadualkan. Tiada salin-tampal antara aplikasi.",
    "Illustration. Product screenshots coming.":"Ilustrasi. Tangkapan skrin produk akan datang.",
    "WhatsApp auto reply from your own documents":"Balasan automatik WhatsApp daripada dokumen anda sendiri",
    "Upload PDFs and add your website pages so replies draw on your real content, not general knowledge.":"Muat naik PDF dan tambah halaman laman web supaya balasan menggunakan kandungan sebenar anda, bukan pengetahuan umum.",
    "A built-in CRM that remembers every customer":"CRM terbina dalam yang mengingati setiap pelanggan",
    "Every conversation writes back to a CRM record with tags, status and staff assignment.":"Setiap perbualan direkodkan semula dalam CRM bersama tag, status dan tugasan kakitangan.",
    "Built for":"Dibina untuk",
    "Answer enquiries and collect bookings in the chat":"Jawab pertanyaan dan kumpulkan tempahan dalam sembang",
    "Agencies":"Agensi",
    "Run broadcasts for several client brands from separate workspaces, each with its own channels, contacts and knowledge base.":"Jalankan siaran untuk beberapa jenama pelanggan dari ruang kerja berasingan, masing-masing dengan saluran, kenalan dan pangkalan pengetahuan sendiri.",
    "Online stores":"Kedai dalam talian",
    "Send order updates and restock alerts to WhatsApp, then let the bot answer follow-up questions from your product documentation.":"Hantar kemas kini pesanan dan makluman stok semula ke WhatsApp, kemudian biarkan bot menjawab soalan susulan berdasarkan dokumentasi produk anda.",
    "Service businesses":"Perniagaan perkhidmatan",
    "Let the chatbot collect booking requests on WhatsApp, Telegram or your website chat. Your staff confirm each one, and the list downloads as a CSV file.":"Biarkan chatbot mengumpulkan permintaan tempahan melalui WhatsApp, Telegram atau sembang laman web. Kakitangan anda mengesahkan setiap permintaan, dan senarai boleh dimuat turun sebagai fail CSV.",
    "Support teams":"Pasukan sokongan",
    "Answer repeat questions from your own help articles, and let your staff pick up the rest with the full conversation history.":"Jawab soalan berulang berdasarkan artikel bantuan anda dan biarkan kakitangan mengendalikan selebihnya dengan sejarah perbualan penuh.",
    "WhatsApp, Telegram and website chat in one inbox":"WhatsApp, Telegram dan sembang laman web dalam satu peti masuk",
    "The official WhatsApp Business API. Connect your own number through Meta embedded signup.":"WhatsApp Business API rasmi. Sambungkan nombor anda melalui pendaftaran terbenam Meta.",
    "Add a bot token and start publishing to channels and groups.":"Tambah token bot dan mula menerbitkan ke saluran serta kumpulan.",
    "Route WhatsApp traffic through a Wasender session.":"Halakan trafik WhatsApp melalui sesi Wasender.",
    "A chat widget for your own website and a shareable chat link are included as well, and neither uses a channel slot.":"Widget sembang untuk laman web anda dan pautan sembang yang boleh dikongsi turut disertakan, dan kedua-duanya tidak menggunakan slot saluran.",
    "In development":"Dalam pembangunan",
    "Instagram, Facebook, X and LinkedIn are not available yet. They are on the roadmap and are not included in any plan today.":"Instagram, Facebook, X dan LinkedIn belum tersedia. Semuanya berada dalam pelan pembangunan dan belum disertakan dalam mana-mana pelan.",
    "Under the hood":"Di sebalik sistem",
    "Knowledge base, automation and one inbox":"Pangkalan pengetahuan, automasi dan satu peti masuk",
    "Knowledge base":"Pangkalan pengetahuan",
    "Upload documents and scrape pages; replies cite what you gave it.":"Muat naik dokumen dan ekstrak halaman; balasan memetik kandungan yang anda berikan.",
    "Automation":"Automasi",
    "Route conversations through decision flows instead of manual triage.":"Halakan perbualan melalui aliran keputusan dan bukan pengagihan manual.",
    "Broadcast":"Siaran",
    "One message fans out to a segmented audience.":"Satu mesej dihantar kepada khalayak yang telah disegmentasikan.",
    "Unified inbox":"Peti masuk bersepadu",
    "Every channel lands in the same conversation view.":"Setiap saluran masuk ke paparan perbualan yang sama.",
    "Where things stand":"Status semasa",
    "What Omnexa does today":"Apa yang Omnexa lakukan hari ini",
    "Channels live — WhatsApp Cloud API, Telegram, Wasender":"Saluran aktif — WhatsApp Cloud API, Telegram, Wasender",
    "In development — Instagram, Facebook, X, LinkedIn":"Dalam pembangunan — Instagram, Facebook, X, LinkedIn",
    "Grounded":"Berasaskan sumber",
    "Replies cite documents you upload":"Balasan memetik dokumen yang anda muat naik",
    "One inbox":"Satu peti masuk",
    "Every channel in the same conversation view":"Setiap saluran dalam paparan perbualan yang sama",
    "We built Omnexa because running broadcasts across WhatsApp and Telegram meant three tools and a spreadsheet. It should be one composer. If something is missing for your team, tell us and we will build it.":"Kami membina Omnexa kerana mengurus siaran di WhatsApp dan Telegram memerlukan tiga alat serta satu hamparan. Sepatutnya semuanya dilakukan dalam satu penyunting. Jika pasukan anda memerlukan sesuatu, beritahu kami dan kami akan membinanya.",
    "— Founder, Omnexa":"— Pengasas, Omnexa",
    "Before you sign up":"Sebelum anda mendaftar",
    "A Malaysian company.":"Syarikat Malaysia.",
    "Omnexa is operated by Meta Realty Sdn Bhd (SSM 202201040486), Puchong, Selangor.":"Omnexa dikendalikan oleh Meta Realty Sdn Bhd (SSM 202201040486), Puchong, Selangor.",
    "Prices in Ringgit, shown in full.":"Harga dalam Ringgit dan dipaparkan sepenuhnya.",
    "Every plan and its limits are listed below. Starting the 7-day trial needs no card.":"Setiap pelan dan hadnya disenaraikan di bawah. Percubaan 7 hari tidak memerlukan kad.",
    "The official WhatsApp API.":"WhatsApp API rasmi.",
    "Connect through Meta's WhatsApp Cloud API, or use a Wasender session if you prefer.":"Sambung melalui WhatsApp Cloud API Meta, atau gunakan sesi Wasender jika anda mahu.",
    "Your team stays in control.":"Pasukan anda kekal mengawal.",
    "Staff can read and reply to any conversation from the same inbox.":"Kakitangan boleh membaca dan membalas mana-mana perbualan dari peti masuk yang sama.",
    "Your customers' data.":"Data pelanggan anda.",
    "We do not sell personal data to advertisers. Read our":"Kami tidak menjual data peribadi kepada pengiklan. Baca",
    "privacy policy":"dasar privasi kami",
    ", also in":", juga dalam",
    "Bahasa Malaysia":"Bahasa Malaysia",
    ".":".",
    "Chatbot + GEO pricing in Malaysian Ringgit":"Harga Chatbot + GEO dalam Ringgit Malaysia",
    "Paid plans bundle Chatbot and GEO.":"Pelan berbayar menggabungkan Chatbot dan GEO.",
    "Choose a 1, 3, 6 or 12-month term and pay the full term upfront. AI credit and GEO allowances still reset every month; one provider check means one combined keyword topic sent to one AI-search platform. Every new account starts with a 7-day Free trial, with no card required; usage beyond the included AI credit is billed separately.":"Pilih tempoh 1, 3, 6 atau 12 bulan dan bayar jumlah penuh lebih awal. Kredit AI dan elaun GEO masih ditetapkan semula setiap bulan; satu semakan penyedia bermaksud satu topik kata kunci gabungan dihantar ke satu platform carian AI. Setiap akaun baharu bermula dengan percubaan Free 7 hari tanpa kad; penggunaan melebihi kredit AI yang disertakan dicaj berasingan.",
    "Choose a billing term":"Pilih tempoh bil",
    "Subscription term":"Tempoh langganan",
    "1 month":"1 bulan",
    "3 months":"3 bulan",
    "6 months":"6 bulan",
    "12 months":"12 bulan",
    "/ month equivalent":"/ nilai bulanan",
    "charged upfront for a":"dibayar lebih awal untuk tempoh",
    "-month term · Save":"bulan · Jimat",
    "Prices are monthly, in Malaysian Ringgit.":"Harga adalah bulanan, dalam Ringgit Malaysia.",
    "Every new account starts with a 7-day free trial of the Free plan, with no card required. To keep AI replies on after the trial, choose a paid plan. Every plan includes an AI credit allowance, and usage beyond the allowance is billed separately. Paid plans also include a separate monthly GEO allowance; one provider check means one combined keyword topic sent to one AI-search platform.":"Setiap akaun baharu bermula dengan percubaan percuma 7 hari bagi pelan Free, tanpa kad. Untuk meneruskan balasan AI selepas percubaan, pilih pelan berbayar. Setiap pelan termasuk elaun kredit AI, dan penggunaan melebihi elaun dicaj berasingan. Pelan berbayar juga termasuk elaun GEO bulanan berasingan; satu semakan penyedia bermaksud satu topik kata kunci gabungan dihantar ke satu platform carian AI.",
    "7-day free trial only":"Percubaan percuma 7 hari sahaja",
    "1 bot":"1 bot",
    "1 channel":"1 saluran",
    "1 seat":"1 tempat duduk",
    "3 knowledge files, 50 MB":"3 fail pengetahuan, 50 MB",
    "RM 1 AI credit for the trial":"Kredit AI RM 1 untuk percubaan",
    "AI models: 1 entry model":"Model AI: 1 model permulaan",
    "Chat booking requests":"Permintaan tempahan melalui sembang",
    "Start 7-day trial":"Mulakan percubaan 7 hari",
    "5 knowledge files, 50 MB":"5 fail pengetahuan, 50 MB",
    "RM 5 AI credit monthly":"Kredit AI RM 5 sebulan",
    "AI models: GPT-6 Luna, Gemini 3.8 Flash":"Model AI: GPT-6 Luna, Gemini 3.8 Flash",
    "GEO: 10 provider checks monthly":"GEO: 10 semakan penyedia sebulan",
    "5 live GEO APIs":"5 API GEO langsung",
    "AI-derived bot persona":"Persona bot terbitan AI",
    "Conversation memory":"Memori perbualan",
    "2 bots":"2 bot",
    "2 channels":"2 saluran",
    "3 seats":"3 tempat duduk",
    "25 knowledge files, 250 MB":"25 fail pengetahuan, 250 MB",
    "RM 20 AI credit monthly":"Kredit AI RM 20 sebulan",
    "AI models: GPT-6 Luna, Gemini 3.8 Flash, Claude Haiku 4.5":"Model AI: GPT-6 Luna, Gemini 3.8 Flash, Claude Haiku 4.5",
    "GEO: 40 provider checks monthly":"GEO: 40 semakan penyedia sebulan",
    "Up to 10 keywords per GEO analysis":"Sehingga 10 kata kunci bagi setiap analisis GEO",
    "CRM lead assignment":"Tugasan prospek CRM",
    "Single website scraping":"Pengekstrakan satu laman web",
    "AI-assisted menu generation":"Penjanaan menu dibantu AI",
    "Guided knowledge ingestion":"Kemasukan pengetahuan berpandu",
    "3 bots":"3 bot",
    "4 channels":"4 saluran",
    "5 seats":"5 tempat duduk",
    "75 knowledge files, 1 GB":"75 fail pengetahuan, 1 GB",
    "RM 60 AI credit monthly":"Kredit AI RM 60 sebulan",
    "AI models: GPT-6.1 Sol, Claude Sonnet 5.5, Gemini 3.1 Pro":"Model AI: GPT-6.1 Sol, Claude Sonnet 5.5, Gemini 3.1 Pro",
    "GEO: 120 provider checks monthly":"GEO: 120 semakan penyedia sebulan",
    "AI-generated reports":"Laporan dijana AI",
    "Automation workflows":"Aliran kerja automasi",
    "Knowledge refinement Q&A":"Soal jawab pemurnian pengetahuan",
    "Batch website scraping":"Pengekstrakan laman web secara kelompok",
    "Availability booking":"Tempahan mengikut slot kosong",
    "Questions":"Soalan",
    "WhatsApp AI chatbot questions, answered":"Jawapan kepada soalan chatbot AI WhatsApp",
    "What is Omnexa?":"Apakah Omnexa?",
    "Omnexa combines an AI chatbot and GEO analysis for small and medium businesses in Malaysia. Paid plans start from RM 89 per month equivalent on a 12-month prepaid term.":"Omnexa menggabungkan chatbot AI dan analisis GEO untuk perusahaan kecil dan sederhana di Malaysia. Pelan berbayar bermula daripada nilai bulanan RM 89 untuk tempoh prabayar 12 bulan.",
    "How much does a WhatsApp AI chatbot cost with Omnexa?":"Berapakah harga chatbot AI WhatsApp dengan Omnexa?",
    "For a one-month term, Essential costs RM 133.50, Advanced RM 283.50 and Pro RM 561.00. Lower monthly equivalents are available for 3, 6 and 12-month prepaid terms. Every new account starts with a 7-day Free trial, with no card required.":"Untuk tempoh satu bulan, Essential berharga RM 133.50, Advanced RM 283.50 dan Pro RM 561.00. Nilai bulanan yang lebih rendah tersedia untuk tempoh prabayar 3, 6 dan 12 bulan. Setiap akaun baharu bermula dengan percubaan Free 7 hari tanpa kad.",
    "How do I add an AI chatbot to my business WhatsApp?":"Bagaimanakah saya menambah chatbot AI pada WhatsApp perniagaan?",
    "Sign up, then connect your number through the official WhatsApp Cloud API or a Wasender session. Upload PDFs or add your website pages, and Omnexa starts answering customers from that content and saving each conversation to its CRM.":"Daftar, kemudian sambungkan nombor anda melalui WhatsApp Cloud API rasmi atau sesi Wasender. Muat naik PDF atau tambah halaman laman web, dan Omnexa mula menjawab pelanggan berdasarkan kandungan itu serta menyimpan setiap perbualan dalam CRM.",
    "Where does the chatbot get its answers?":"Dari manakah chatbot mendapatkan jawapannya?",
    "From the documents you upload and the website pages you add, rather than general knowledge, so replies reflect what your business has actually published.":"Daripada dokumen yang anda muat naik dan halaman laman web yang anda tambah, bukan pengetahuan umum, supaya balasan mencerminkan kandungan sebenar yang diterbitkan oleh perniagaan anda.",
    "Can my staff reply instead of the bot?":"Bolehkah kakitangan saya membalas bagi pihak bot?",
    "Yes. Every conversation lands in one inbox next to its CRM record, with tags, status and staff assignment, so your team can read the full history and reply to the customer directly.":"Ya. Setiap perbualan masuk ke satu peti masuk bersama rekod CRM, tag, status dan tugasan kakitangan, supaya pasukan anda boleh membaca sejarah penuh dan membalas pelanggan secara langsung.",
    "Can customers book appointments through the chat?":"Bolehkah pelanggan membuat tempahan melalui sembang?",
    "Yes. Once you switch bookings on for a chatbot, it collects booking requests in the chat. Your staff confirm each request, and the full list downloads as a CSV file.":"Ya. Selepas tempahan diaktifkan untuk chatbot, ia mengumpulkan permintaan tempahan dalam sembang. Kakitangan anda mengesahkan setiap permintaan, dan senarai penuh boleh dimuat turun sebagai fail CSV.",
    "Which channels does Omnexa support?":"Saluran manakah yang disokong oleh Omnexa?",
    "WhatsApp (through the official Cloud API or a Wasender session), Telegram and a chat widget for your own website are live today. Instagram, Facebook, X and LinkedIn are in development and are not included in any plan yet.":"WhatsApp (melalui Cloud API rasmi atau sesi Wasender), Telegram dan widget sembang untuk laman web anda tersedia hari ini. Instagram, Facebook, X dan LinkedIn masih dalam pembangunan dan belum disertakan dalam mana-mana pelan.",
    "Do I need a Meta Business account?":"Adakah saya memerlukan akaun Meta Business?",
    "Yes, for the WhatsApp Cloud API. Telegram needs only a bot token, which takes about a minute to create, and the website chat needs no outside account.":"Ya, untuk WhatsApp Cloud API. Telegram hanya memerlukan token bot yang mengambil masa kira-kira seminit untuk dicipta, manakala sembang laman web tidak memerlukan akaun luar.",
    "Which AI models does Omnexa use?":"Model AI manakah yang digunakan oleh Omnexa?",
    "Essential includes GPT-6 Luna and Gemini 3.8 Flash. Advanced adds Claude Haiku 4.5. Pro includes GPT-6.1 Sol, Claude Sonnet 5.5 and Gemini 3.1 Pro. The 7-day free trial uses one entry model. On paid plans you choose which included model each chatbot uses.":"Essential merangkumi GPT-6 Luna dan Gemini 3.8 Flash. Advanced menambah Claude Haiku 4.5. Pro merangkumi GPT-6.1 Sol, Claude Sonnet 5.5 dan Gemini 3.1 Pro. Percubaan percuma 7 hari menggunakan satu model permulaan. Dalam pelan berbayar, anda memilih model yang disertakan untuk setiap chatbot.",
    "Berapakah harga chatbot AI WhatsApp untuk bisnes di Malaysia?":"Berapakah harga chatbot AI WhatsApp untuk bisnes di Malaysia?",
    "Omnexa menggabungkan chatbot AI dan analisis GEO untuk perniagaan di Malaysia. Pelan berbayar bermula daripada nilai bulanan RM 89 dengan tempoh prabayar 12 bulan. Setiap akaun baharu bermula dengan percubaan percuma 7 hari, tanpa kad.":"Omnexa menggabungkan chatbot AI dan analisis GEO untuk perniagaan di Malaysia. Pelan berbayar bermula daripada nilai bulanan RM 89 dengan tempoh prabayar 12 bulan. Setiap akaun baharu bermula dengan percubaan percuma 7 hari, tanpa kad.",
    "Put an AI chatbot on your WhatsApp today":"Pasang chatbot AI pada WhatsApp anda hari ini",
    "Connect WhatsApp, Telegram or your website, upload your documents, and let Omnexa answer your customers.":"Sambungkan WhatsApp, Telegram atau laman web anda, muat naik dokumen, dan biarkan Omnexa menjawab pelanggan anda.",
    "WhatsApp AI chatbot, CRM and broadcasts for Malaysian businesses.":"Chatbot AI WhatsApp, CRM dan siaran untuk perniagaan Malaysia.",
    "Product":"Produk",
    "Company":"Syarikat",
    "About":"Tentang kami",
    "Contact":"Hubungi",
    "Resources":"Sumber",
    "Legal":"Perundangan",
    "Privacy":"Privasi",
    "Terms":"Terma",
    "Omnexa. Operated by Meta Realty Sdn Bhd (SSM 202201040486), Malaysia.":"Omnexa. Dikendalikan oleh Meta Realty Sdn Bhd (SSM 202201040486), Malaysia.",
    "Go to your bots":"Pergi ke bot anda",
    "View plans":"Lihat pelan",
    "Language":"Bahasa",
    "Switch to light mode":"Tukar kepada mod cerah",
    "Switch to dark mode":"Tukar kepada mod gelap",
    "Omnexa product demonstration showing an AI customer agent conversation":"Demonstrasi produk Omnexa yang menunjukkan perbualan ejen pelanggan AI",
    "A single message splitting through a prism into separate channel streams":"Satu mesej berpecah melalui prisma kepada aliran saluran berasingan",
    "Document pages folding into a reply bubble, linked by glowing filaments":"Halaman dokumen dilipat menjadi gelembung balasan yang dihubungkan oleh filamen bercahaya",
    "A contact card orbited by tags and status rings":"Kad kenalan dikelilingi tag dan gelang status",
    "The robot routing messages into three client workspaces":"Robot menghalakan mesej ke tiga ruang kerja pelanggan",
    "The robot handing a parcel toward an order-update message":"Robot menyerahkan bungkusan ke arah mesej kemas kini pesanan",
    "The robot placing a checkmark on a calendar slot":"Robot meletakkan tanda semak pada slot kalendar",
    "The robot lifting a document sheet into a reply bubble":"Robot mengangkat helaian dokumen ke dalam gelembung balasan",
    "The robot holding a glowing chat bubble":"Robot memegang gelembung sembang bercahaya",
    "The robot releasing a paper-plane of light":"Robot melepaskan kapal terbang kertas bercahaya",
    "The robot beside a relay tower emitting signal rings":"Robot di sisi menara geganti yang memancarkan gelang isyarat",
    "A lattice of document shards forming an index sphere":"Kekisi serpihan dokumen membentuk sfera indeks",
    "A node graph with one path lit brighter":"Graf nod dengan satu laluan bercahaya lebih terang",
    "A core pulsing outward into many points of light":"Teras berdenyut keluar menjadi banyak titik cahaya",
    "Separate streams converging into one channel":"Aliran berasingan bergabung ke satu saluran",
    "Scroll to explore":"Tatal untuk meneroka",
    "AI customer agent":"Ejen pelanggan AI",
    "Every customer answered in seconds":"Setiap pelanggan dijawab dalam beberapa saat",
    "Replies on WhatsApp, Telegram and your website chat, day and night, using your own PDFs and web pages.":"Membalas di WhatsApp, Telegram dan sembang laman web anda, siang dan malam, berdasarkan PDF dan halaman web anda sendiri.",
    "CRM and analytics":"CRM dan analitik",
    "Every chat becomes a lead you can see":"Setiap sembang menjadi prospek yang jelas kelihatan",
    "Contacts, conversations and bookings land in one built-in CRM, with reports on what customers ask.":"Kenalan, perbualan dan tempahan masuk ke satu CRM terbina dalam, dengan laporan tentang soalan pelanggan.",
    "Automation workflow":"Aliran kerja automasi",
    "Follow-ups that run themselves":"Susulan yang berjalan sendiri",
    "Route new leads to the right teammate and trigger the next step automatically.":"Hantar prospek baharu kepada rakan sepasukan yang betul dan cetuskan langkah seterusnya secara automatik.",
    "See it run":"Lihat ia berjalan",
    "One enquiry, a complete workflow":"Satu pertanyaan, satu aliran kerja lengkap",
    "Watch an enquiry move from the WhatsApp inbox to a routed workflow and into GEO insight.":"Lihat satu pertanyaan bergerak dari peti masuk WhatsApp ke aliran kerja yang diagihkan dan seterusnya ke cerapan GEO.",
    "Product demo with illustrative data.":"Demo produk dengan data ilustrasi."
  };

  const PRESERVE=new Set([
    "Omnexa","WhatsApp Cloud API","Telegram","Wasender","Instagram","Facebook","X","LinkedIn","FAQ","VO",
    "Free","Essential","Advanced","Pro","RM 0","RM 89","RM 133.50","RM 283.50","RM 561.00","25%","30%","35%","50%","1","3","4","6","12","©",
    "English","简体中文","Bahasa Melayu","Bahasa Malaysia",".","1 bot","☀","☾",
    "Berapakah harga chatbot AI WhatsApp untuk bisnes di Malaysia?",
    "Omnexa menggabungkan chatbot AI dan analisis GEO untuk perniagaan di Malaysia. Pelan berbayar bermula daripada nilai bulanan RM 89 dengan tempoh prabayar 12 bulan. Setiap akaun baharu bermula dengan percubaan percuma 7 hari, tanpa kad."
  ]);
  const dictionaries={"zh-CN":ZH,ms:MS};
  const textRecords=[];
  const attributeRecords=[];
  const translatableAttributes=["aria-label","alt","placeholder","title"];
  let activeLanguage="en";

  function keyOf(value){return String(value||"").replace(/\s+/g," ").trim();}
  function isPreserved(key){return PRESERVE.has(key)||/^\d{4}$/.test(key);}
  function translated(key,language){
    if(language==="en") return EN_OVERRIDES[key]||key;
    return (dictionaries[language]&&dictionaries[language][key])||key;
  }
  function withOriginalSpacing(raw,value){
    const leading=(raw.match(/^\s*/)||[""])[0];
    const trailing=(raw.match(/\s*$/)||[""])[0];
    return leading+value+trailing;
  }
  function collect(){
    const walker=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);
    let node;
    while((node=walker.nextNode())){
      const parent=node.parentElement;
      if(!parent||parent.closest("script,style,noscript,svg,select,option")) continue;
      const key=keyOf(node.nodeValue);
      if(key) textRecords.push({node,key,raw:node.nodeValue});
    }
    document.querySelectorAll("[aria-label],[alt],[placeholder],[title]").forEach(function(element){
      translatableAttributes.forEach(function(attribute){
        if(element.id==="theme-toggle"&&(attribute==="aria-label"||attribute==="title")) return;
        const raw=element.getAttribute(attribute);
        const key=keyOf(raw);
        if(key) attributeRecords.push({element,attribute,key});
      });
    });
  }
  function updateThemeControl(){
    const button=document.getElementById("theme-toggle");
    const glyph=document.getElementById("theme-glyph");
    if(!button||!glyph) return;
    const light=document.documentElement.dataset.theme==="light";
    const label=translated(light?"Switch to dark mode":"Switch to light mode",activeLanguage);
    button.setAttribute("aria-label",label);
    button.setAttribute("title",label);
    glyph.textContent=light?"☾":"☀";
  }
  function applyTheme(theme,persist){
    const next=theme==="light"?"light":"dark";
    document.documentElement.dataset.theme=next;
    const meta=document.getElementById("theme-color");
    if(meta) meta.setAttribute("content",next==="light"?"#F6F5F1":"#060A12");
    if(persist!==false){try{localStorage.setItem("omnexa-theme",next);}catch(e){}}
    updateThemeControl();
  }
  function applyLanguage(language,persist){
    const next=language==="zh-CN"||language==="ms"?language:"en";
    activeLanguage=next;
    const missing=[];
    textRecords.forEach(function(record){
      const value=translated(record.key,next);
      record.node.nodeValue=withOriginalSpacing(record.raw,value);
      if(next!=="en"&&value===record.key&&!isPreserved(record.key)) missing.push(record.key);
    });
    attributeRecords.forEach(function(record){
      const value=translated(record.key,next);
      record.element.setAttribute(record.attribute,value);
      if(next!=="en"&&value===record.key&&!isPreserved(record.key)) missing.push(record.key);
    });
    document.documentElement.lang=next;
    const select=document.getElementById("language-select");
    if(select) select.value=next;
    if(persist!==false){try{localStorage.setItem("omnexa-language",next);}catch(e){}}
    updateThemeControl();
    window.__OMNEXA_I18N_MISSING__=[...new Set(missing)];
    document.dispatchEvent(new CustomEvent("omnexa:languagechange",{detail:{language:next}}));
  }

  collect();
  const languageSelect=document.getElementById("language-select");
  const themeToggle=document.getElementById("theme-toggle");
  if(languageSelect) languageSelect.addEventListener("change",function(){applyLanguage(this.value,true);});
  if(themeToggle) themeToggle.addEventListener("click",function(){
    applyTheme(document.documentElement.dataset.theme==="light"?"dark":"light",true);
  });
  let savedLanguage="en";
  try{savedLanguage=localStorage.getItem("omnexa-language")||"en";}catch(e){}
  applyTheme(document.documentElement.dataset.theme,false);
  applyLanguage(savedLanguage,false);
  window.OmnexaPreferences={setLanguage:applyLanguage,setTheme:applyTheme};
})();
