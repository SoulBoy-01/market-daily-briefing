# 国际数据提供方候选调研与许可核查（2026-10-05）

- 状态：调研完成，待所有者拍板
- 日期：2026-10-05
- 前置阅读：ADR 0001（真实来源访问与零预算准入）、ADR 0004（真实来源黄金案例）、[国内源调研](2026-10-05-source-license-research.md)（国内结论：交易所官方腿待定可用，独立 API 腿国内无合格候选——本文只为补上这条「独立腿」）
- 调研方式：条款页与文档页直接抓取（curl / 浏览器渲染，2026-10-04/05 执行）；公开端点行为实测（curl + 浏览器）；全部结论落在主来源（条款原文 URL、官方文档、端点实测响应），未凭二手转述下结论
- 范围说明：本项目需要的是**每日收盘点位与涨跌幅（EOD）**，非实时行情；本地、非商业、单维护者用途

---

## 一、调研问题与判定标准

S1–S5 与国内调研完全一致（ADR 0001 / 0004）：条款必须清晰（S4）、黄金案例必须包含**许可允许保存的原始响应**（S5）、独立腿必须与交易所官方腿做逐指数双源核对（S2）。

本文新增两条任务级硬约束：

| 编号 | 标准 | 说明 |
| --- | --- | --- |
| I1 | **必须覆盖全部三个指数**（000001.SH / 399001.SZ / 399006.SZ） | 独立腿要和官方腿逐指数核对，缺任何一个即不合格（可作降级参考，不算合格候选） |
| I2 | **「非官方 API」（爬官网、逆向接口）必须标注 ToS 状态** | 多数 ToS 禁止程序化访问，这类不算合格候选；查不到书面条款写「条款不清晰」，不猜测 |

另外两个结构问题（A 上游授权链、B 更新时滞）见第三、四节。付费源在 ADR 0001 零预算下不得启用（S4），但所有者正在考虑修订 ADR 放开小额付费，故本文列出价格。

---

## 二、候选逐项判定

### 3.1 FRED（圣路易斯联储，fred.stlouisfed.org）

**覆盖三指数？** 否。站内搜索（2026-10-05 快照）只找到上海系列：`SPASTT01CHM661N`「Share Prices for China」（页面注明 Shanghai Stock Exchange: SSE Composite Index），**月频**、1955-01 至 **2024-01**（页面显示最近一次更新 2025-11-17，即数据已停止更新超过一年半）、OECD MEI 来源。**未发现深证成指、创业板指序列，未发现任何日频中国股指序列**（含 OPEN779 在内的猜测 ID 经 HTTP 探测均不存在或无法访问）。

**免费额度**：免费注册 + API Key；限 120 请求 / 6 分钟（API 条款页）。

**条款**：[FRED API Terms of Use](https://fred.stlouisfed.org/docs/api/terms_of_use.html) 关键句（经页面渲染提取，启用前应再存一次原文快照）：

> 存储：自检索之日起，通过 FRED API 获取的 FRED 数据最多可存储 **6 个月**，之后必须删除或重新获取……

> **天气预报数据**及其他选定数据由第三方数据提供方提供，**本行（圣路易斯联储）没有再分发这些数据的许可**。此类内容仅可用于内部、非商业、不可转让目的……被标记为 DNR（"Do Not Redistribute"）的内容不得转载。

**存储许可**：有条件允许（6 个月时限 + 第三方内容可能落入 DNR 限制；OECD 序列是否属 DNR 需在 fred-groups 列表核对——本次未核到明确标记，不猜）。

**更新时滞**：月频且长期滞后，与逐日核对完全无关。

**结论：不符合（I1 硬性不合格）**。缺两个指数、非日频、数据停更 1.5 年以上。零预算下它本来是最干净的免费授权链（公共机构、许可条款明文），可惜覆盖完全错位。

### 3.2 Yahoo Finance（finance.yahoo.com，含 yfinance）

**覆盖三指数？** 是。实测（2026-10-05，curl 直连 `query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=5d&interval=1d`，无需登录）：`000001.SS`（SSE Composite Index）、`399001.SZ`（Shenzhen Index）、`399006.SZ`（ChiNext）三个 ticker 均返回日线 OHLC 与涨跌幅字段（`regularMarketChangePercent` 等）。数据覆盖与最近交易日同国内假期安排一致。

**官方 API？** 无。Yahoo 官方开发者条款目录（[Yahoo Terms 索引页](https://policies.yahoo.com/us/en/yahoo/terms/index.htm)）中现存 API 条款仅覆盖 OpenID / YQL（已废）/ BOSS / Maps 等，**没有任何行情数据 API**。`query1/query2.finance.yahoo.com` 是网站内部接口，不是「已发布的接口」。

**条款**：[Yahoo Terms of Service](https://legal.yahoo.com/us/en/yahoo/terms/otos/index.html)（Member conduct / Use of Services 节，浏览器渲染提取）：

> access or collect data, or attempt to access or collect data, from our Services using **any automated means**, devices, programs, algorithms or methodologies, including but not limited to robots, spiders, **scrapers**, data mining tools, or data gathering or extraction tools, **for any purpose without our express, prior permission**.

> You must not misuse or interfere with the Services or **try to access them using a method other than the interface and the instructions that we provide**.

同节还禁止：use any material or content from, including without limitation any data, (a) **to create any database, archive, mobile application, data feed, widget or any other aggregated data source** that competes with or constitutes a material substitute for the Services…

**存储许可**：不允许（未经明确事先许可的自动化访问本身已违规；建库存档条款属明文禁止类）。

**yfinance 的法律地位**：其官方 [GitHub README](https://github.com/ranaroussi/yfinance) 自带免责声明（逐字）：

> **Intended for personal use only. Do not use commercially.** / **This is not an official Yahoo API.** No warranties provided. / **Can break anytime without notice.** / **May be in violation of Yahoo's Terms of Use. Use at your own risk.**

即作者本人承认该库可能违反 Yahoo ToS。按 I2，这不构成合格候选。

**更新时滞**：无任何书面时滞承诺（非官方接口，Yahoo 无义务维持其可用性或时点）。

**结论：不符合**。覆盖满分、零成本，但程序化访问与存档均被 ToS 明文禁止；且 Yahoo 曾多次对第三方客户端强制 cookie/crumb，接口随时可被封锁（不可作为正式来源）。若所有者愿意接受「灰色降级参考」，它只能作为人工抽查对照，不能登记为正式独立腿。

### 3.3 Stooq（stooq.com）

**覆盖三指数？** 否。实测：`^SHC` = Shanghai Composite Index - China 存在；`^szc` 及「shenzhen / chinext / 399001」符号搜索均无结果（搜索页实测 2026-10-05）；其批量历史数据库页（[stooq.com/db/h/](https://stooq.com/db/h/)）目录仅有 World / U.S. / U.K. / Japan / Hong Kong / Poland / Hungary / Macroeconomy，**没有中国大陆文件夹**。

**条款**：**有书面 ToS**（[stooq.com/terms.html](https://stooq.com/terms.html)）：

> 5.3. Redistribution of data found on the website is **not allowed without the consent of Stooq**.

> 6.1（S&P Dow Jones 指数许可条款）The Index data may be used only for **your own personal, non-commercial purposes**.

其批量数据页另有明示：「This data is intended solely for **personal use**. Any commercial use is prohibited.」

**存储许可**：条款只禁「未经同意的再分发」，未明文授权也未明文禁止本地保存（与 S5 的「许可允许保存」相比仍欠一层明文，但明显比东财/腾讯宽松）。条款仅向 S&P DJI、LME 两个上游作了许可披露，**中国指数数据上游未披露**。

**程序化访问**：无明文授权；实测其 CSV 端点（`q/d/l/`）从本环境返回「Access denied」，页面访问需通过 JS 反爬挑战——自动化读取事实上受限。

**更新时滞**：无书面承诺。

**结论：不符合（I1 硬性不合格）**。只有上证综指，缺深证成指与创业板指。作为免费个人参考数据可用，但进不了双源核对体系。

### 3.4 Alpha Vantage（alphavantage.co）

**覆盖三指数？** 未确认，且关键端点锁付费。官方文档（[alphavantage.co/documentation](https://www.alphavantage.co/documentation/)）确认中国**个股**支持（示例 ticker `600104.SHH`、`000002.SHZ`、`300135.SHZ`）；**指数端点 INDEX_DATA 明示为 Premium**（逐字）：

> 💡 Tip: this is a **premium API endpoint**. Subscribe to any of our 150, 300, 600, or 1200 requests per minute premium plans to instantly unlock this endpoint.

其「Other Major Indices / Index Catalog」是否含上证综指、深证成指、创业板指，需注册后调 Index Catalog 才能确认——**不能免 key 验证，不猜**。

**免费额度**：免费 Key 存在（每日请求配额以官网支持页/后台为准，本次未在文档页核到确切数字原文）。免费 Key **不含** INDEX_DATA。

**条款**：`https://www.alphavantage.co/terms_of_service/` 实际返回 **PDF 文件**（本次环境无法安全解析其全文，存档为 `/tmp/av_terms.pdf`）。对存储/再利用的具体条款**未提取、未引用**——按任务规则此处标「条款未核全文」，不猜测。

**存储许可 / 再展示**：未核全文，未判定。

**更新时滞**：文档对 GLOBAL_QUOTE 的表述（逐字）："by default, the quote endpoint is updated **at the end of each trading day** for all users"。指数端点的时点无单独说明。

**结论：不符合（S4 付费门槛 + I1 未确认）**。即使付费解锁 INDEX_DATA，中国三大指数是否在目录中仍未确认；且条款未核全文。若所有者想深挖，步骤是：注册 → 查 Index Catalog → 读 PDF 条款。

### 3.5 Twelve Data（twelvedata.com）

**覆盖三指数？** 待注册确认。其市场列表页（[twelvedata.com/markets](https://twelvedata.com/markets)）含上海/深圳交易所（渲染后可见；静态 HTML 与本次浏览器渲染均不稳定，**需注册后用 `/exchanges`/`/markets` API 精确复核**，指数符号 000001/399001/399006 的存在性同样待确认）。定价页按套餐限定「Markets」数量：免费层仅 3 个市场（逐字 "Markets 85 76 27 3"，对应 Business/Pro/Grow/Basic 四档），中国交易所大概率在付费档。

**免费额度**：免费层「8 API credits/分钟（800 次/天）」（定价页逐字），且数据用途受限（见下）。

**条款**：[Twelve Data Terms of Use](https://twelvedata.com/terms)（Last updated: January 1, 2026，主体为新加坡 Twelve Data Pte. Ltd.）。关键原文：

> 2.2 Data license: Customer is granted a limited, non-exclusive license to: **(a) Access, receive, process, and store Data solely for Internal Use** … (b) Display Data to Authorized Users … (e) Redistribute or provide external display of Data **only if and as expressly authorized by a Redistribution Rights Add-On** or separate written agreement…

> 2.3 Restrictions: … (g) **Store or cache Data beyond permitted timeframes specified in the Documentation** … (b) Redistribute, resell, sublicense, or transfer any Data … to third parties …

> 12.5(b) Upon termination: Customer must **delete all Data**（16.2 要求 30 天内删除）。

**定价页对各档数据用途的原文**（title tooltip，2026-10-05 提取）：

> 免费层（Basic Free）：**"Data may be used internally for testing, evaluation, or development purposes only. The data cannot be displayed to users, shared externally, or used in production systems."**

> 付费层：**"Use the data internally for programmatic processing, analysis, system integration, and internal display. The data may not be redistributed or made available to external parties."**

另一条付费档 tooltip 为 "View-only access… may be displayed but **cannot be programmatically processed, stored, transformed, or redistributed**"（该条与哪一档对应需注册后在账户页确认）。

**存储许可**：**条款不清晰（偏严）**。付费层允许「内部处理 + 内部展示」，本地非商业展示可落在这层；但 (a) 条款引用「Documentation 中规定的存储时限」，而文档（twelvedata.com/docs 全文检索）**并未写明任何存储时限**——引用落空；(b) 终止后 30 天删除全部数据的义务与黄金案例「永久留存原始响应」存在张力；(c) 若项目所用档位适用 "cannot be programmatically processed, stored" 的 view-only 限定，则直接违反 S5。三处疑点需向其法务/销售书面确认或注册实测。

**更新时滞**：定价页描述 EOD 数据 "updated **after each exchange close**"，无中国交易所具体时点。

**价格**（定价页）：Basic Free $0（3 市场、仅测试评估用途）；Grow $29/mo；Pro $99/mo；Business $329/mo 起。

**结论：待定（条款不清晰 + 覆盖待确认，按 S4 不得启用）**。比 EODHD 多三处不确定（存储时限落空、档位限定、覆盖未验证）。

### 3.6 EOD Historical Data / EODHD（eodhd.com）——重点核实对象

**覆盖三指数？** 部分确认。其符号搜索页（eodhd.com/search?q=000001）确认交易所存在：**Shanghai Stock Exchange（SHG / XSHG）**、**Shenzhen Stock Exchange（SHE / XSHE）**。三大指数的具体符号格式（`.IND` 后缀体系下的确切代码，如 SHCOMP.IND 或 000001.SHG）**未能免登录确认**——demo token 对中国交易所的 symbol list 返回 Forbidden（实测），需注册后核实。交易所覆盖 + 指数体系存在是高概率，但按任务规则此处记「待注册确认」。

**价格**（[eodhd.com/pricing](https://eodhd.com/pricing)，2026-10-05 提取）：Sandbox **$0**（免费）；EOD Historical / All-World **$19.99/mo**（$199/年）；EOD + Intraday / All-World Extended **$29.99/mo**（$299.90/年）；Fundamentals $59.99/mo；ALL-IN-ONE $99.99/mo。**中国交易所（SHG/SHE）落在哪一档需注册后确认**（其历史文档惯例是中国市场在 All World Extended 档）。

**条款**：[EODHD Terms and Conditions](https://eodhd.com/financial-apis/terms-conditions)。这是全部候选中**唯一明文允许保存数据**的商业条款（逐字）：

> A Non-Professional User is an individual who views or uses EOD Historical Data Information **solely in a personal capacity for their own personal investment activities**. Non-Professional Users do not act as principals, officers, partners, employees, contractors, or agents of any business…

> **Non-Professional Users are permitted to store, manipulate, and analyze the data for private, non-commercial purposes.** However, they are prohibited from: Sharing access to their account with others, including within groups. **Selling, reselling, retransmitting, redistributing, displaying, or granting access to the Information or Services, whether in its original or repackaged form.**

配套事实：单 key 每日 100,000 次 API 请求；本项目每日盘后 3 次调用（三个指数）远低于所有限额。本地审查界面属于「非对外授予访问」，不落入 prohibited 枚举；但「displaying」一词出现在禁止清单里（语义指向对外展示/授予访问），**建议在来源登记时书面记录这一解释**，必要时邮件向 EODHD 确认。

**数据质量警示（来自 EODHD 自己的披露，非常关键）**（条款页与全站页脚，逐字）：

> All CFDs (**stocks, indices**, mutual funds, ETFs), cryptocurrencies, and Forex are **not provided by exchanges but rather by market makers**, and so prices **may not be accurate and may differ from the actual market price**, meaning prices are indicative and not appropriate for trading purposes.

其[数据来源页](https://eodhd.com/financial-apis/our-data-sources-and-data-partners)只对美（Nasdaq Cloud API）、欧（Cboe Europe）、澳（ASX 直授）、加 NEO/TSX（Quotemedia）披露了交易所直授合同，并称可应订阅者要求提供合同证明；随后说明 **"Another end-of-day (EOD) and delayed (LIVE) API data comes from CFDs and market makers."**——**未提及与中国任何交易所或数据商的合同**。这意味着其中国指数收盘价很可能来自做市商/CFD 通道，与官方交易所收盘值之间**没有制度性一致保证**（可能有微小偏差或不同的收盘定义）。这正是它条款宽松的结构性原因（见第三节）。

**更新时滞**（[EOD API 文档](https://eodhd.com/financial-apis/api-for-historical-data-and-volumes)，逐字）：

> We update each stock exchange **2-3 hours after the market closes**. Major US exchanges, NYSE and NASDAQ, are updated within 15 minutes after the market closes. US mutual funds, PINK, OTCBB, **and some indices update only the next morning**…

若中国指数适用「收盘后 2-3 小时」（15:00 CST 收盘 → 约 17:00–18:00 CST 可取），EODHD **可以参与当日盘后核对**；但「some indices update only the next morning」这一例外是否覆盖中国指数，**必须注册后连续观测数日**才能定论（见开放问题）。

**结论：待定（唯一值得推进的付费候选）**。条款允许存储（S5 通过）、程序化访问即产品设计（S1/S3 通过）、更新时滞理论上可支持当日核对；缺的是 I1 实测确认（三个指数符号与数值质量）与所有者对 ADR 0001 零预算的修订决定。**它也可能是假阴性：若实测发现其中国指数值与官方收盘系统性偏差，则双源核对永远过不了，只能弃用。**

### 3.7 快速通过组（Marketstack / Finnhub / FMP / Tiingo / Polygon / Barchart）

#### Marketstack（marketstack.com，apilayer/Idera 旗下）

- 覆盖：官网只宣称 "Nasdaq, NYSE, and more"（首页逐字），**未见任何中国内地交易所覆盖证据**（首页/文档 grep 无 Shanghai/Shenzhen/SSE/SZSE）。
- 条款：`marketstack.com/terms` 重定向至 [ideracorp.com/legal/APILayer](https://www.ideracorp.com/legal/APILayer)（JS 渲染，本次**未取得条款全文**，标「条款不清晰」）。
- 免费额度：有免费档（具体以官网为准），但覆盖已不过关。
- **结论：不符合（I1）**。

#### Finnhub（finnhub.io）

- 覆盖：以美股为主的产品定位；官方文档交易所清单未见上海/深圳（未实测 symbol list，需 key）。
- 条款（[finnhub.io/terms-of-service](https://finnhub.io/terms-of-service)，逐字）：

  > **All data must be deleted should your subscription to that data ends.** It is your responsibility to comply with any copyright laws…

  > **You hereby agree to not redistribute or share access to data or derived results from the data obtained from Finnhub with anyone or any 3rd party without written approval from Finnhub. All plan listed on Finnhub website is strictly for personal use** unless explicitly stated otherwise. Personal plan can't be used by any business even internally without a written approval.

- 存储许可：未授予持久保存权；订阅结束即须删除全部数据——与黄金案例永久留存的架构相抵触。
- **结论：不符合（I1 + S5）**。

#### Financial Modeling Prep（FMP，financialmodelingprep.com）

- 覆盖：官方文档（developer/docs，2026-10-05 提取）中 **无 Shanghai/Shenzhen/SSE/SZSE/XSHG 任何命中**；指数端点为 "live quotes for global indexes"（美股系为主）。
- 条款（terms-of-service，逐字节选）：

  > This license is **personal to the Customer**, and the Customer may not share FMP Services or Data, resell, permit other users access to our Services through the Customer's account, **integrate the Data or Services into any tools or applications accessible by any third parties**, or use the Services to host, share, display, or provide content for others.

  另有 2.8 条要求客户申报所有存有 FMP 数据的存储位置 IP/域名并接受安全审查——存档虽被默许架构，但无明文保存许可，且未授予再展示权。
- **结论：不符合（I1 + 条款偏严）**。

#### Tiingo（tiingo.com）

- 覆盖：美股/ETF/共同基金 + 外汇/加密的产品定位，无中国内地指数（官网页本次为 JS 空壳，未能抓到覆盖声明原文，据其产品结构判定；如需引证可注册后查 `/tiingo/daily` 目录）。
- 条款（[tiingo.com/tos](https://www.tiingo.com/tos) §1.6，逐字——**全部候选中最严**）：

  > (a) Starter Plans and Trial Plans… **you may not write, save, archive, back up, or otherwise retain Tiingo Data in any persistent or durable storage**. You may process Tiingo Data only transiently in volatile memory…

  > (b) Paid Plans. While an eligible paid subscription plan… remains active, you may persist Tiingo Data in storage solely to the extent permitted by that Paid Plan… Upon the expiration, cancellation, or termination of the Paid Plan… you must **promptly and permanently delete all Tiingo Data from every system**… including production systems, local storage, logs, queues, archives, backups, disaster-recovery systems…

- 免费层明文禁止持久存储；付费层订阅终止即全库删除——与审计快照/黄金案例（须长期留存、可复算哈希）根本冲突。
- **结论：不符合（I1 + S5 硬冲突）**。

#### Polygon.io（已更名 Massive，massive.com）

- 覆盖：官方文档（massive.com/docs/stocks，逐字）："At Massive, we provide a comprehensive suite of **U.S. stock market data**… coverage of the **U.S. stock market landscape**… all 19 major stock exchanges, additional dark pools, FINRA trading facilities, and OTC markets."——**纯美国市场，无中国指数**。条款页为 JS 应用（本次未提取全文）。
- **结论：不符合（I1）**。

#### Barchart OnDemand（barchart.com）

- 覆盖：官网与 OnDemand 页面未发现中国指数覆盖声明（站内搜索被反爬，未能确认；其全球数据集以往含中国指数但本次未能验证，不猜）。
- 条款（[barchart.com/terms](https://www.barchart.com/terms)，逐字）：

  > …for your **personal, non-commercial use only**: You may use Barchart Content offered for downloading… Your computer may **temporarily store copies of Barchart content in RAM** incidental to your accessing and viewing such Content. You may store files that are automatically cached by your web browser…

  > …YOU AGREE NOT TO **REPRODUCE, RETRANSMIT, DISSEMINATE, SELL, DISTRIBUTE, PUBLISH, BROADCAST OR CIRCULATE** ANY OF THE BARCHART SERVICES OR CONTENT… WITHOUT THE PRIOR EXPRESS WRITTEN CONSENT OF BARCHART AND/OR THE DATA PROVIDERS.

- 存储许可：仅 RAM 临时副本 + 浏览器缓存——**保存原始响应入审计快照直接越界**。
- 免费额度：无公开免费 API 档（首页为 "Try Barchart for Free" 试用引导，旧 OnDemand 150 次/天免费档未见现行入口）。
- **结论：不符合（S5）**。

### 3.8 Investing.com（investing.com）——预期不合格，确认

条款（[Terms and Conditions](https://www.investing.com/about-us/terms-and-conditions)，浏览器渲染提取，逐字）：

> **It is prohibited to use, store, reproduce, display, modify, transmit or distribute the data contained in this website without the explicit prior written permission of Fusion Media and/or the data provider.** All intellectual property rights are reserved by the providers and/or the exchange providing the data contained in this website.

use / store / reproduce / display 四项全禁，前置条款还自认其行情「prices are indicative and not appropriate for trading purposes」（CFD 做市商通道，与 EODHD 同源问题的免费版）。

**结论：不符合（S5 直接否决，与预期一致）**。

---

## 三、结构问题 A：上游授权链——国际源的中国指数数据从哪来？

按披露透明度分三档：

| 档位 | 来源 | 披露内容 | 性质 |
| --- | --- | --- | --- |
| 披露明确 | FRED | 序列来自 OECD（第三方）；FRED 自身声明对部分第三方内容「没有再分发许可」（DNR 机制） | 有授权链，但受 DNR 类约束 |
| 披露明确且**不含中国** | EODHD | 美/欧/澳交易所直授 + Quotemedia（加）；**「其余 EOD/延迟数据来自 CFD 与做市商」且「indices」被其条款页脚明确归入该类**；可应要求提供合同证明——但未提及任何中国合同 | 对中国市场：**无可验证授权，须「信任其合规」，且数值来源是做市商而非交易所** |
| 未披露 | Yahoo / Stooq / Alpha Vantage / Twelve Data / 其余 | Yahoo 只称内容「由我们或数据提供方许可，仅用于在 Yahoo 服务上展示」；Stooq 仅披露 S&P DJI 与 LME；其余无中国上游说明 | 全部依赖「信任其合规」 |

**关键判断**：没有任何一个候选披露了对中国交易所（上证所信息网络有限公司 / 深圳证券信息有限公司）或中证指数公司的再授权。国内源被交易所法律声明锁死（东财第十条），国际源则普遍走**做市商/CFD/聚合商通道绕开交易所行情知识产权**——这解释了它们为什么敢给宽松条款（EODHD 明文允许存储、Investing.com 同源数据却全禁）。对本项目的实际含义：

1. 双源核对的价值从「两个独立授权来源互证」降级为「官方值 vs 做市商衍生值」——**数值一致性没有任何制度保证，必须实测**（EODHD 自己都说 prices "may differ from the actual market price"）。
2. 即便 EODHD 通过 S5，其上游授权链也无法被本项目审计；来源登记必须把这一点记录为「已接受的风险」（与国内调研开放问题 1 的「解释风险」同性质：所有者书面接受，或放弃该腿）。

## 四、结构问题 B：更新时滞——独立腿能否参与当日盘后核对？

| 来源 | 书面时滞承诺 | 评估 |
| --- | --- | --- |
| EODHD | 「每个交易所收盘后 2-3 小时更新」（美股大所 15 分钟；「部分指数」次日早上） | 若实测中国指数适用 2-3 小时：15:00 收盘 → **约 17:00–18:00 CST 可取 → 可参与当日盘后核对**；「部分指数次日早上」的例外是否覆盖中国指数需连续观测数日 |
| Twelve Data | EOD 数据 "updated after each exchange close"（无小时数） | 理论上可当日，需实测 |
| Alpha Vantage | quote 端点 "updated at the end of each trading day"（指数端点付费且覆盖未确认） | 不适用 |
| Yahoo / Stooq / Marketstack 等 | 无书面承诺 | 不可依赖 |
| FRED | 月频 + 停更 1.5 年 | 完全不能参与逐日核对 |

**结论**：在唯一候选 EODHD 上，当日盘后核对**理论可行但需实测定论**。若实测为 T+1（落入「部分指数次日早上」例外），则独立腿只能做 T+1 补充核对——简报当日仍以官方腿单源发布 + 次日回溯核对，这将改变 ADR 0001 决策 2 的「同日双源核对」含义，需要所有者预先接受。这一点必须写进来源登记与黄金案例的覆盖说明。

---

## 五、结论与推荐

**核心问题的明确回答：本次调研的所有候选中，没有任何一家同时满足「三个指数全覆盖（已验证）+ 条款允许保存响应（明文）」。**

- 免费候选全灭：FRED 缺覆盖（月频/停更/缺两指数）、Stooq 缺覆盖（仅上证）、Yahoo/Stooq 之外的非官方接口（yfinance）被 Yahoo ToS 明文禁止（I2 不合格）。
- 付费候选中只有一家值得推进：**EODHD**（条款明文允许非专业用户存储数据、价格 $19.99–29.99/mo、交易所列表含沪/深、时滞可当日），但其三大指数的**符号存在性与数值质量均未实测**，且其自认指数数据来自做市商而非交易所——存在实测后否决的可能性。Twelve Data 为次选（三处条款疑点）。

**若所有者决定修订 ADR 0001 放开小额付费**，推荐路径：

1. **EODHD 一个月实测期**（$19.99 All-World 档先行；若中国指数要求 Extended 档再升级）：注册 → 确认三大指数符号 → 连续 10 个交易日拉取收盘值与官方腿逐日核对 → 观测更新时点（当日 2-3 小时口径 vs T+1）→ 全程保存原始响应（条款允许）。全部通过后才写来源登记、进入 ADR 0004 黄金案例建设。
2. 若 EODHD 数值与官方收盘系统性偏差 → 弃用，回到「真实模式保持禁用」（ADR 0001 决策 5），或评估 Twelve Data（先书面确认其存储时限疑点）。
3. 不建议为 Yahoo/yfinance 之类的非官方接口「降级准入」——ToS 明禁 + 接口随时被封，不符合本项目的审计初衷。

## 六、仍需所有者拍板的开放问题

1. **是否修 ADR 放开小额付费**（约 $20–30/月 ≈ ¥150–220/月）：这是国际独立腿的唯一可行路径；若维持零预算，国际调研结论就是「无合格候选」，真实模式继续禁用。
2. **EODHD「displaying」一词的解释**：其非专业条款把 "displaying" 列入对外禁止清单（与 sell/resell/redistribute 并列）。本地单维护者审查界面不构成对外展示，但建议启用前邮件向 support@eodhistoricaldata.com 书面确认并留存回复。
3. **EODHD 中国指数是否落入「部分指数次日早上更新」例外**：注册后连续观测 5–10 个交易日的首次可得时点，决定其参与当日核对还是 T+1 回溯核对（影响 ADR 0001 决策 2 的同日双源核对语义）。
4. **Alpha Vantage 溯源**：其条款为 PDF（本次未提取全文）；若 EODHD 失败且要评估 AV，需先读 PDF 条款 + Index Catalog 确认中国指数存在性。
5. **国际源条款失效监控**：与国内调研开放问题 5 合并——所有引用的条款页快照日期为 2026-10-05，建议来源登记加入「条款页定期复查 + 哈希比对」。

---

## 附：本次调研抓取与实测记录

| 来源 | URL | 用途 |
| --- | --- | --- |
| FRED 系列页 | https://fred.stlouisfed.org/series/SPASTT01CHM661N | 3.1 覆盖（月频/OECD/停更） |
| FRED API 条款 | https://fred.stlouisfed.org/docs/api/terms_of_use.html | 3.1 存储 6 个月 / DNR |
| Yahoo ToS | https://legal.yahoo.com/us/en/yahoo/terms/otos/index.html （自 https://policies.yahoo.com/us/en/yahoo/terms/index.htm ） | 3.2 自动化访问禁令 |
| yfinance README | https://github.com/ranaroussi/yfinance | 3.2 免责声明逐字 |
| Yahoo chart API 实测 | https://query1.finance.yahoo.com/v8/finance/chart/{000001.SS,399001.SZ,399006.SZ}?range=5d&interval=1d | 3.2 三指数覆盖实测（curl，2026-10-05） |
| Stooq 报价页/符号搜索 | https://stooq.com/q/?s=^shc 、 /q/s/?s=shenzhen 等 | 3.3 ^SHC 存在、深证/创业板无 |
| Stooq 条款 / 批量数据库页 | https://stooq.com/terms.html 、 https://stooq.com/db/h/ | 3.3 条款、无中国目录 |
| Alpha Vantage 文档 | https://www.alphavantage.co/documentation/ | 3.4 INDEX_DATA Premium、中国个股 ticker |
| Alpha Vantage 条款 | https://www.alphavantage.co/terms_of_service/ （实为 PDF） | 3.4 未提取全文 |
| Twelve Data 条款 | https://twelvedata.com/terms | 3.5 2.2/2.3/12.5/16 原文 |
| Twelve Data 定价页 | https://twelvedata.com/pricing | 3.5 四档价格/市场数/用途 tooltip |
| Twelve Data 文档全文检索 | https://twelvedata.com/docs | 3.5 「存储时限见文档」落空证据 |
| EODHD 条款 | https://eodhd.com/financial-apis/terms-conditions | 3.6 非专业用户存储许可原文 |
| EODHD 数据来源页 | https://eodhd.com/financial-apis/our-data-sources-and-data-partners | 3.6/三节A 上游披露 |
| EODHD EOD API 文档 | https://eodhd.com/financial-apis/api-for-historical-data-and-volumes | 3.6/四节B 2-3 小时时滞原文 |
| EODHD 定价/搜索页 | https://eodhd.com/pricing 、 https://eodhd.com/search?q=000001 | 3.6 价格、SHG/XSHG + SHE/XSHE |
| Finnhub 条款 | https://finnhub.io/terms-of-service | 3.7 删除/禁再分发/个人用途原文 |
| FMP 条款/文档 | https://site.financialmodelingprep.com/terms-of-service 、 /developer/docs | 3.7 个人许可、无中国覆盖 |
| Tiingo ToS | https://www.tiingo.com/tos | 3.7 §1.6 存储禁令原文 |
| Massive (Polygon) 文档 | https://massive.com/docs/stocks | 3.7 US-only 原文 |
| Barchart 条款 | https://www.barchart.com/terms | 3.7 RAM/缓存限制原文 |
| Investing.com 条款 | https://www.investing.com/about-us/terms-and-conditions | 3.8 use/store 全禁原文 |
| Marketstack 首页 | https://marketstack.com/ | 3.7 覆盖证据（无中国）；条款页（ideracorp）JS 渲染未取得全文 |

端点实测均为 2026-10-04/05（UTC+8）执行；所有条款引用为当日快照，正式启用任何来源前应重新抓取原文存档并做哈希登记（呼应国内调研开放问题 5）。
