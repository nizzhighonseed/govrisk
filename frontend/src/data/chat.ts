export const suggestedQuestions: string[] = [
  'Which projects are at highest risk?',
  'Why is the River Basin Development Project high risk?',
  'Which sector has the highest average cost overrun?',
  'Show me projects likely to be delayed.',
  'What are the major risk drivers?',
];

export const mockResponses: Record<string, string> = {
  'which projects are at highest risk':
    'Based on the current portfolio analysis, 143 projects are classified as high risk. The three highest-risk projects requiring immediate attention are:\n\n' +
    '1. **River Basin Development Project** (Bihar) — Risk Score: 91/100\n' +
    '   - Delay Probability: 88%\n' +
    '   - Cost Overrun: 21.3%\n' +
    '   - Status: Critical\n\n' +
    '2. **Smart City Mission - Bhubaneswar** (Odisha) — Risk Score: 89/100\n' +
    '   - Delay Probability: 84%\n' +
    '   - Cost Overrun: 24.7%\n' +
    '   - Status: Critical\n\n' +
    '3. **Eastern Dedicated Freight Corridor** (West Bengal) — Risk Score: 79/100\n' +
    '   - Delay Probability: 74%\n' +
    '   - Cost Overrun: 12.7%\n' +
    '   - Status: High\n\n' +
    '**Recommended Action:** These projects should be escalated for immediate review by the monitoring committee.',

  'why is the river basin development project high risk':
    'The **River Basin Development Project** in Bihar carries a risk score of 91/100 due to multiple compounding factors:\n\n' +
    '- **Severe Schedule Slippage:** Physical progress is at 34% against a planned 72%, indicating a 38-point gap.\n' +
    '- **Delay Probability: 88%** — Predicted completion is 14 months beyond the April 2025 deadline.\n' +
    '- **Cost Overrun: 21.3%** — Original sanctioned cost of ₹4,200 Cr has escalated to an estimated ₹5,094 Cr.\n' +
    '- **Milestone Failures:** 9 of 14 milestones (64%) have been missed in the last two quarterly reviews.\n' +
    '- **Risk Factors:** Land acquisition disputes in 3 districts, contractor resource mobilization delays, and monsoon-impacted foundation work.\n\n' +
    '**Recommendation:** Deploy an on-site monitoring team and initiate stakeholder mediation for land acquisition issues.',

  'which sector has the highest average cost overrun':
    'Across all monitored sectors, the **Water** sector has the highest average cost overrun:\n\n' +
    '| Sector | Avg Cost Overrun | Project Count |\n' +
    '|---|---|---|\n' +
    '| **Water** | **18.4%** | 47 |\n' +
    '| Transport | 14.2% | 89 |\n' +
    '| Energy | 11.7% | 63 |\n' +
    '| Mining | 9.8% | 28 |\n' +
    '| Social Infrastructure | 7.3% | 52 |\n' +
    '| Communication | 5.1% | 34 |\n\n' +
    "The Water sector's elevated overrun is largely driven by 6 major irrigation projects in Bihar and Uttar Pradesh facing repeated geotechnical surprises and land acquisition delays. Together these 6 projects account for ₹3,800 Cr in cumulative overruns.",

  'show me projects likely to be delayed':
    'The following projects have a **delay probability above 70%** and require urgent intervention:\n\n' +
    '1. **River Basin Development Project** (Bihar) — 88% delay probability\n' +
    '   - Predicted delay: 14 months | Physical progress: 34%\n\n' +
    '2. **Delhi-Mumbai Industrial Corridor Phase II** (Maharashtra) — 82% delay probability\n' +
    '   - Predicted delay: 11 months | Physical progress: 41%\n\n' +
    '3. **Smart City Mission - Bhubaneswar** (Odisha) — 84% delay probability\n' +
    '   - Predicted delay: 10 months | Physical progress: 38%\n\n' +
    '4. **North-Eastern Regional Power Grid** (Assam) — 76% delay probability\n' +
    '   - Predicted delay: 8 months | Physical progress: 52%\n\n' +
    '5. **Eastern Dedicated Freight Corridor** (West Bengal) — 74% delay probability\n' +
    '   - Predicted delay: 7 months | Physical progress: 48%\n\n' +
    '**Summary:** 38 projects across the portfolio exceed the 70% delay probability threshold, representing ₹1.2 lakh Cr in total sanctioned cost.',

  'what are the major risk drivers':
    'Analysis of 313 monitored projects reveals the following top risk drivers ranked by frequency and impact:\n\n' +
    '1. **Land Acquisition Delays** — Affects 42% of high-risk projects (60 projects)\n' +
    '   - Primary in Water and Transport sectors\n' +
    '   - Avg impact: +8.2 months delay\n\n' +
    '2. **Contractor Performance Issues** — Affects 31% of high-risk projects (44 projects)\n' +
    '   - Resource mobilization gaps and labor shortages\n' +
    '   - Avg impact: +5.6 months delay\n\n' +
    '3. **Geotechnical/Environmental Surprises** — Affects 24% of high-risk projects (34 projects)\n' +
    '   - Unexpected soil conditions, flooding, environmental clearances\n' +
    '   - Avg impact: +6.1 months delay\n\n' +
    '4. **Budgetary Shortfalls / Fund Release Delays** — Affects 19% of high-risk projects (27 projects)\n' +
    '   - Delayed/releases from Ministry of Finance\n' +
    '   - Avg impact: ₹340 Cr per project\n\n' +
    '5. **Regulatory and Clearance Bottlenecks** — Affects 15% of high-risk projects (21 projects)\n' +
    '   - Forest clearance, forest diversion, and pollution control board approvals\n\n' +
    '**Key Insight:** Land acquisition remains the single largest systemic risk. Projects with proactive land acquisition planning show 47% lower delay probability.',

  "portfolio overview":
    "Here is a snapshot of the **GovRisk monitored portfolio** as of September 2025:\n\n" +
    "- **Total Projects Monitored:** 313\n" +
    "- **Total Sanctioned Cost:** ₹8.7 lakh Cr\n" +
    "- **Total Expenditure to Date:** ₹4.1 lakh Cr (47.1%)\n\n" +
    "**Risk Distribution:**\n" +
    "- Critical: 52 projects (16.6%)\n" +
    "- High: 91 projects (29.1%)\n" +
    "- Medium: 118 projects (37.7%)\n" +
    "- Low: 52 projects (16.6%)\n\n" +
    "**Performance Metrics:**\n" +
    "- Average Physical Progress: 54.3%\n" +
    "- Average Planned Progress: 68.1%\n" +
    "- Schedule Variance: -13.8 percentage points\n" +
    "- Average Cost Overrun: 11.2%\n" +
    "- Projects Delayed (>70% probability): 38\n\n" +
    "**Trend:** Risk levels have increased by 4.2% over the last quarter, primarily driven by the Water and Transport sectors.",

  'sector comparison':
    'Here is a comparative analysis of risk across sectors:\n\n' +
    '| Sector | Projects | Avg Risk | Avg Cost Overrun | Avg Delay (months) |\n' +
    '|---|---|---|---|---|\n' +
    '| **Water** | 47 | 62.4 | 18.4% | 9.2 |\n' +
    '| **Transport** | 89 | 58.1 | 14.2% | 7.8 |\n' +
    '| **Energy** | 63 | 51.3 | 11.7% | 5.4 |\n' +
    '| **Mining** | 28 | 47.6 | 9.8% | 4.9 |\n' +
    '| **Social Infrastructure** | 52 | 42.8 | 7.3% | 3.6 |\n' +
    '| **Communication** | 34 | 38.2 | 5.1% | 2.8 |\n\n' +
    '**Key Findings:**\n' +
    '- The Water sector underperforms on all three risk dimensions — it has the highest average risk, cost overrun, and delay.\n' +
    '- Transport has the largest volume of projects (89) and contributes the most to the absolute count of high-risk projects (38).\n' +
    '- Communication sector projects show the strongest performance with the lowest risk and minimal delays.\n\n' +
    '**Recommendation:** Prioritize portfolio review meetings for Water and Transport sector projects with risk scores above 65.',

  'ministry performance':
    'Ministry-wise performance ranking based on weighted risk scores (lower is better):\n\n' +
    '| Rank | Ministry | Projects | Avg Risk | High/Critical Projects |\n' +
    '|---|---|---|---|---|\n' +
    '| 1 | Ministry of Jal Shakti | 34 | 64.7 | 18 |\n' +
    '| 2 | Ministry of Road Transport & Highways | 52 | 57.3 | 24 |\n' +
    '| 3 | Ministry of Railways | 28 | 53.1 | 12 |\n' +
    '| 4 | Ministry of Power | 31 | 48.9 | 10 |\n' +
    '| 5 | Ministry of Coal | 19 | 46.2 | 7 |\n' +
    '| 6 | Ministry of Education | 22 | 41.4 | 5 |\n' +
    '| 7 | Ministry of Health & Family Welfare | 18 | 39.8 | 4 |\n' +
    '| 8 | Ministry of Communications | 15 | 35.6 | 2 |\n\n' +
    '**Observations:**\n' +
    '- Ministry of Jal Shakti has the highest concentration of critical projects (18), driven largely by irrigation and river basin projects in Bihar and UP.\n' +
    '- Ministry of Road Transport & Highways manages the largest portfolio (52 projects) with a 46% high/critical rate.\n' +
    '- Ministry of Communications maintains the best risk profile with only 2 high-risk projects across 15 monitored initiatives.\n\n' +
    '**Action Required:** The monitoring committee should schedule dedicated reviews for Jal Shakti and Road Transport ministries this quarter.',

  "hello":
    "Hello! I'm the **GovRisk AI Assistant**, here to help you analyze government infrastructure project risks.\n\n" +
    "I can assist you with:\n" +
    "- **Portfolio Risk Analysis** — View overall risk distribution and trends\n" +
    "- **Project Deep Dives** — Drill into specific project risk factors\n" +
    "- **Sector Comparisons** — Compare risk metrics across sectors\n" +
    "- **Ministry Performance** — Review ministry-wise project outcomes\n" +
    "- **Predictive Insights** — Get AI-powered delay and cost overrun predictions\n" +
    "- **Recommendations** — Receive actionable mitigation strategies\n\n" +
    "Try asking me about high-risk projects, cost overruns, or sector performance to get started.",

  "help":
    "Here's how I can help you navigate the GovRisk platform:\n\n" +
    "**Project Analysis:**\n" +
    "- \"Which projects are at highest risk?\"\n" +
    "- \"Show me projects likely to be delayed.\"\n" +
    "- \"Why is [project name] high risk?\"\n\n" +
    "**Sector & Ministry Insights:**\n" +
    "- \"Which sector has the highest average cost overrun?\"\n" +
    "- \"Compare sector performance.\"\n" +
    "- \"How is [ministry name] performing?\"\n\n" +
    "**Risk Intelligence:**\n" +
    "- \"What are the major risk drivers?\"\n" +
    "- \"Give me a portfolio overview.\"\n" +
    "- \"What's the cost prediction for [project name]?\"\n\n" +
    "**Tips:**\n" +
    "- You can click on any suggested question below the chat for quick access.\n" +
    "- Responses reference real-time data from the monitored portfolio of 313 projects.\n" +
    "- For detailed project views, click on any project card in the dashboard.",

  'cost prediction':
    'Based on our predictive cost model, here are the top projects at risk of significant cost overruns:\n\n' +
    '1. **River Basin Development Project** (Bihar)\n' +
    '   - Current Cost: ₹5,094 Cr | Original: ₹4,200 Cr\n' +
    '   - Predicted Final Cost: ₹5,340 Cr\n' +
    '   - Cost Overrun Probability: 92%\n\n' +
    '2. **Smart City Mission - Bhubaneswar** (Odisha)\n' +
    '   - Current Cost: ₹1,870 Cr | Original: ₹1,500 Cr\n' +
    '   - Predicted Final Cost: ₹2,010 Cr\n' +
    '   - Cost Overrun Probability: 87%\n\n' +
    '3. **Delhi-Mumbai Industrial Corridor Phase II** (Maharashtra)\n' +
    '   - Current Cost: ₹12,400 Cr | Original: ₹10,800 Cr\n' +
    '   - Predicted Final Cost: ₹13,100 Cr\n' +
    '   - Cost Overrun Probability: 81%\n\n' +
    '4. **Eastern Dedicated Freight Corridor** (West Bengal)\n' +
    '   - Current Cost: ₹8,950 Cr | Original: ₹7,940 Cr\n' +
    '   - Predicted Final Cost: ₹9,420 Cr\n' +
    '   - Cost Overrun Probability: 76%\n\n' +
    '**Portfolio-Wide Forecast:** Total estimated cost overrun across all high-risk projects is ₹23,400 Cr (cumulative). The model uses physical progress trends, milestone completion rates, and historical overrun patterns.',

  'high risk':
    'Based on the current portfolio analysis, 143 projects are classified as high risk. The three highest-risk projects requiring immediate attention are:\n\n' +
    '1. **River Basin Development Project** (Bihar) — Risk Score: 91/100\n' +
    '   - Delay Probability: 88%\n' +
    '   - Cost Overrun: 21.3%\n' +
    '   - Status: Critical\n\n' +
    '2. **Smart City Mission - Bhubaneswar** (Odisha) — Risk Score: 89/100\n' +
    '   - Delay Probability: 84%\n' +
    '   - Cost Overrun: 24.7%\n' +
    '   - Status: Critical\n\n' +
    '3. **Eastern Dedicated Freight Corridor** (West Bengal) — Risk Score: 79/100\n' +
    '   - Delay Probability: 74%\n' +
    '   - Cost Overrun: 12.7%\n' +
    '   - Status: High\n\n' +
    '**Recommended Action:** These projects should be escalated for immediate review by the monitoring committee.',

  delayed:
    'The following projects have a **delay probability above 70%** and require urgent intervention:\n\n' +
    '1. **River Basin Development Project** (Bihar) — 88% delay probability\n' +
    '   - Predicted delay: 14 months | Physical progress: 34%\n\n' +
    '2. **Delhi-Mumbai Industrial Corridor Phase II** (Maharashtra) — 82% delay probability\n' +
    '   - Predicted delay: 11 months | Physical progress: 41%\n\n' +
    '3. **Smart City Mission - Bhubaneswar** (Odisha) — 84% delay probability\n' +
    '   - Predicted delay: 10 months | Physical progress: 38%\n\n' +
    '4. **North-Eastern Regional Power Grid** (Assam) — 76% delay probability\n' +
    '   - Predicted delay: 8 months | Physical progress: 52%\n\n' +
    '5. **Eastern Dedicated Freight Corridor** (West Bengal) — 74% delay probability\n' +
    '   - Predicted delay: 7 months | Physical progress: 48%\n\n' +
    '**Summary:** 38 projects across the portfolio exceed the 70% delay probability threshold, representing ₹1.2 lakh Cr in total sanctioned cost.',

  'risk drivers':
    'Analysis of 313 monitored projects reveals the following top risk drivers ranked by frequency and impact:\n\n' +
    '1. **Land Acquisition Delays** — Affects 42% of high-risk projects (60 projects)\n' +
    '   - Primary in Water and Transport sectors\n' +
    '   - Avg impact: +8.2 months delay\n\n' +
    '2. **Contractor Performance Issues** — Affects 31% of high-risk projects (44 projects)\n' +
    '   - Resource mobilization gaps and labor shortages\n' +
    '   - Avg impact: +5.6 months delay\n\n' +
    '3. **Geotechnical/Environmental Surprises** — Affects 24% of high-risk projects (34 projects)\n' +
    '   - Unexpected soil conditions, flooding, environmental clearances\n' +
    '   - Avg impact: +6.1 months delay\n\n' +
    '4. **Budgetary Shortfalls / Fund Release Delays** — Affects 19% of high-risk projects (27 projects)\n' +
    '   - Delayed releases from Ministry of Finance\n' +
    '   - Avg impact: ₹340 Cr per project\n\n' +
    '5. **Regulatory and Clearance Bottlenecks** — Affects 15% of high-risk projects (21 projects)\n' +
    '   - Forest clearance, wildlife, and pollution control board approvals\n\n' +
    '**Key Insight:** Land acquisition remains the single largest systemic risk. Projects with proactive land acquisition planning show 47% lower delay probability.',

  'immediate intervention':
    'Based on the current portfolio, **143 projects** require some level of attention. Of these, **12 projects are flagged CRITICAL** and should receive immediate intervention this week:\n\n' +
    '1. **River Basin Development Project** (Bihar) — Risk Score: 91/100\n' +
    '   - Delay Probability: 88% | Cost Overrun: 21.3%\n' +
    '   - Why: Physical progress 38 points behind plan, 64% of milestones missed\n\n' +
    '2. **Smart City Mission - Bhubaneswar** (Odisha) — Risk Score: 89/100\n' +
    '   - Delay Probability: 84% | Cost Overrun: 24.7%\n' +
    '   - Why: Contractor mobilization failure and funding shortfall\n\n' +
    '3. **National Highway Development (NH-48 Expansion)** (Maharashtra) — Risk Score: 87/100\n' +
    '   - Delay Probability: 81% | Cost Overrun: 18.4%\n' +
    '   - Why: 11% progress gap and pending land acquisition in 3 stretches\n\n' +
    '4. **Eastern Dedicated Freight Corridor** (West Bengal) — Risk Score: 79/100\n' +
    '   - Delay Probability: 74% | Cost Overrun: 12.7%\n' +
    '   - Why: Milestone delays with rising implementation risk\n\n' +
    '**Recommended Next Step:** Convene the central monitoring committee for the top 4 projects and instruct Ministry heads to submit a recovery plan within 14 days.',

  default:
    "I'm not sure I understand that query. Here are some things I can help with:\n\n" +
    '- Identify the highest-risk projects in the portfolio\n' +
    '- Explain why specific projects are at risk\n' +
    '- Compare risk metrics across sectors\n' +
    '- Analyze ministry-wise performance\n' +
    '- List projects with high delay probability\n' +
    '- Outline the major risk drivers\n' +
    '- Provide portfolio-wide statistics\n\n' +
    'Try rephrasing your question or click on one of the suggested questions below.',
};
