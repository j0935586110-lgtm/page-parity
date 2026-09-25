# page-parity — V1 規格（開源版）

狀態：**已定案**（名稱 `page-parity`、授權 MIT、發佈身分 `j0935586110-lgtm`）
日期：2026-09-25　｜　作者：Hermes（主控）　｜　依據：W1-A 缺陷分類學、W1-C CLI 契約、W1-D 對抗審查、tokens.css 實戰

---

## §0 一句話定位
> **別人回答「畫面有沒有變」；page-parity 回答「這一頁跟大家一樣嗎、有沒有東西擠出畫面」。**
> 使用者 ＝ **剛改完站的人或 agent**；改完自己跑一次，兩秒拿到一個能直接 grep 的結論。

**五個不可退讓的設計前提**
1. **不進部署閘**：它是**診斷**，不是 CI 判準（「沒有人會看 CI」是錯的假設，別再寫進文件）。
2. **預設零網路、零 LLM**：L1 純靜態解析；L2 只在需要時開瀏覽器。
3. **不猜**：不確定 ⇒ `exit 2 INDETERMINATE`，**0 絕不代表「沒檢查到」**。
4. **例外要有理由**：刻意不一致（如轉址頁、工具頁）必須**明列在例外清單並附原因**，不可默默忽略。
5. **公開 V1 只有兩層**：L1 跨頁一致性、L2 元素層溢出。像素回歸／歸因／源碼 diff **不進公開面**（紅海或被先行者覆蓋）。

---

## §1 L1 — 跨頁一致性審計（純 stdlib、秒級、0 token）

### 輸入
`page-parity check --dir <站台目錄>` 或 `--urls <清單檔>`；預設掃 `*.html`（排除 `.git`、`node_modules`）。

### 三項檢查

| # | 檢查 | 方法 | 輸出 |
|---|---|---|---|
| A1 | **應全站一致清單** | 每個項目給「選擇器或文字 pattern」，逐頁數出現次數 | 每項：`出現頁數/總頁數`、缺漏頁清單、值不一致的頁與值 |
| A2 | **變數宣告漂移** | 掃 `<style>` 內 `--x: 值`（**巢狀感知**、去註解），比對同名變數跨頁值 | 同名多值者：變數名、各值、各值所在頁 |
| A3 | **孤兒頁** | 每頁被其他頁 `href` 指到的次數 | 被 0 頁連結者（含是否 `noindex`／轉址頁 → 標為「合理例外」） |

### 內建項目（預設清單，可被設定檔覆寫）
`canonical`／`og:title`／`og:image`／`viewport`／`favicon`／GA 追蹤碼／頁尾聲明文字／選單項目集合／浮水印元素／`lang` 屬性。

### 判準
- 設定檔 `page-parity.toml` 每項可設 `scope = "all" | "min:N" | "any"`；`all` ⇒ 任一頁缺即 `FAIL`
- **例外清單**：`expect_exceptions = [{page="about-v2.html", reason="轉址頁（meta refresh + noindex），刻意不帶選單"}]`
  → 有列理由者不計為失敗，但**一律出現在報告中**（不得沉默）

### 效能
17 頁站台 ≤ **2 秒**（純解析，無瀏覽器）。

---

## §1.1 修訂（v1.1，2026-09-25 由獨立測試套件抓出）
A1 每一項依「出現頁數」分成三類，**只有前兩類影響 exit code**：
| 情況 | 判定 | 影響 exit code |
|---|---|---|
| 全部應有頁都有 | OK | 否 |
| **部分有、部分沒有**（0 < present < 應有） | `INCONSISTENT`（MISSING_ON_PAGE／VALUE_DRIFT） | **是** |
| **全站都沒有**（present == 0） | `ABSENT_EVERYWHERE`（新）**只提示** | **否** |

理由：`watermark` 這類項目在「全站都沒用」的站台不該被判缺陷（否則任何極簡站一跑就有 finding，噪音會殺死工具）；
而我們的真實案例（2/17 頁有）屬於第二類，仍必須報。
證據：F1 最小站（3 頁、無 watermark）原本被判 `MISSING_ON_PAGE missing=3 absent=3` → 獨立測試套件 `test_json_output_single_line` FAIL。

## §2 L2 — 元素層溢出（要瀏覽器，量 layout）

### 兩個層級（**不可混為一談**，這是我們抓到的真實盲區）
- **頁面層**：`documentElement.scrollWidth > clientWidth + tol`（整頁可左右拉）
- **元素層**：某元素 `el.scrollWidth > el.clientWidth + tol`（**頁面不滾，但內容擠出它自己的容器**）
  ← 實例：320px 時 `hero-tags` 容器 288px、內容 298px，**舊閘判 PASS**

### 規格
- 寬度預設 `320,360,390,430,768,1024,1440`；`tol = 2px`（亞像素／反鋸齒容忍，須寫進報告）
- 每個 offender 輸出：`page`、`width`、**CSS 選擇器路徑**（可 grep）、`overflow_px`、元素文字片段
- 另檢 `position: fixed` 元素與互動元素（`a`／`button`）的重疊（可點區域被蓋）
- **成本預算**：17 頁 × 7 寬 ≤ **3 分鐘**；`--widths` 可收斂

---

## §3 CLI 契約（agent-first）

- **預設 `--format=json`**：stdout **單行 JSON**（目標 ≤400 bytes）：`verdict`／`exit_reason`／`codes[]`／`counts{}`／`details_url`
- 人話摘要走 **stderr**（≤3 句）；`--format=human|both` 可選；**禁 ANSI／進度條／表格**（會污染 stdout）
- **exit code**：`0 OK`｜`1 FINDINGS`（確定有不一致）｜`2 INDETERMINATE`（不確定：解析失敗、無輸入、瀏覽器不可用）｜`3 USAGE`｜`4 INTERNAL`
- `codes[]` 枚舉：`MISSING_ON_PAGE`／`VALUE_DRIFT`／`ORPHAN_PAGE`／`ELEMENT_OVERFLOW`／`PAGE_OVERFLOW`／`FIXED_OBSCURES`／`PARSE_ERROR`／`NO_BROWSER`
- `--help` ≤300 字元；`--schema` 吐 JSON Schema；`--self-test` 內建負控制（故意壞掉的樣本必須被判定為 FAIL）
- 一次呼叫拿結論；要細節才 fetch `details_url`

---

## §4 接受標準（**機械可判，缺一不可**）

**A. 功能性**
1. A1/A2/A3 三查各自可單獨跑，且**在已知樣本上給出已知答案**
2. **Oracle 測試（最關鍵）**：在（真實案例站台已去識別化）
   ① 浮水印只 2/17 頁　② 選單／頁尾聲明只 15/17 頁　③ `--dom` 等 scoped 變數**不得**誤報為漂移　④ 孤兒頁 2 頁且標為「合理例外」
3. L2 在 320px 抓出 `hero-tags` 元素層溢出（容器 288／內容 298），並輸出該元素的選擇器路徑
4. **反例測試**：對 `tokens.css` 收斂後的站台跑（單一來源）→ 不得對同一變數報漂移

**B. 契約**
5. `--format=json` 單行、可 `jq` 解析；exit code 符合表；`--help` ≤300 字元；`--schema` 有效
6. `--self-test` 全過（含負控制）

**C. 非功能**
7. L1 ≤2 秒 / 17 頁；L2 ≤3 分鐘 / 17 頁 × 7 寬
8. **零 LLM、零網路**（除 L2 啟動瀏覽器載入本地檔）；`strace` 或等效可證
9. 純 stdlib（L1）＋ `playwright`（L2，可選安裝）；**不得引入其他依賴**

## §5 交付物
```
page-parity/
  README.md            # 首行固定含「cross-page consistency」「layout overflow」兩詞
  llms.txt             # 給 agent 的最小入口（≤30 行）
  AGENTS.md            # agent 使用指南（何時用、怎麼用、輸出怎麼判）
  SKILL.md             # 可被 agent 直接載入的技能卡
  LICENSE              # MIT
  page_parity/         # 套件（L1 純 stdlib；L2 延遲載入 playwright）
  bin/page-parity      # CLI 入口
  page-parity.toml     # 預設檢查清單（可覆寫）
  examples/            # 兩個樣本：乾淨站、已知缺陷站
  tests/               # 由「非實作者」獨立撰寫
  SPEC-V1.md           # 本檔
```

## §6 明確不做
- 不取代 Playwright／BackstopJS 的視覺回歸（**紅海**）
- 不做語意 diff（`qain` 已做且架構更優：CDP DOMSnapshot ＋ `CSS.forcePseudoState` → 直接給 `檔案:行號`；**季度重評**，README 誠實寫「什麼時候該用它」）
- 不做 SaaS、不裝瀏覽器在 CI、不碰客戶站台部署
