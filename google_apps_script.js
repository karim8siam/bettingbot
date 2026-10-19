/**
 * Google Apps Script for SX Bet Quantitative Trading Bot.
 * 
 * Provides automated trade logging, interactive post-trade analytics,
 * and data-driven win/loss diagnostics to continuously improve the model.
 * 
 * Sheets Created:
 * 1. "Analytics Dashboard": Executive KPI cards, Sharpness vs Variance audit,
 *    Performance by Sport, Odds range breakdowns, and Edge calibration tests.
 * 2. "Trades": Granular chronological ledger with automatic CLV (Closing Line Value),
 *    ROI %, and institutional Win/Loss diagnostics.
 */

function setupAll() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var tradesSheet = setupTradesSheet(ss);
  var dashSheet = setupDashboard(ss);
  return { status: "success", message: "Dashboard and Trades sheets configured successfully." };
}

function setupTradesSheet(ss) {
  if (!ss) ss = SpreadsheetApp.getActiveSpreadsheet();
  var sheet = ss.getSheetByName("Trades");
  if (!sheet) {
    sheet = ss.insertSheet("Trades");
  }
  
  var headers = [
    "Timestamp (UTC)",       // Col A (1)
    "Order ID",              // Col B (2)
    "Sport",                 // Col C (3)
    "Event / Match",         // Col D (4)
    "Market Type",           // Col E (5)
    "Selection",             // Col F (6)
    "Odds Taken",            // Col G (7)
    "Model Prob",            // Col H (8)
    "Implied Market Prob",   // Col I (9)
    "Calculated Edge (+EV)", // Col J (10)
    "Strategy Tag",          // Col K (11)
    "Stake ($ USDC)",        // Col L (12)
    "Status",                // Col M (13)
    "Result",                // Col N (14)
    "Net PnL ($)",           // Col O (15)
    "Closing Odds",          // Col P (16)
    "CLV (%)",               // Col Q (17) -> Formula: (OddsTaken / ClosingOdds) - 1
    "Trade ROI (%)",         // Col R (18) -> Formula: Net PnL / Stake
    "Bankroll ($)",          // Col S (19)
    "Engine Diagnostic",     // Col T (20) -> Sharp Win / Lucky Win / Variance Loss / Inefficient
    "Post-Mortem Notes"      // Col U (21) -> Qualitative reflections (injuries, cards, weather)
  ];
  
  sheet.getRange(1, 1, 1, headers.length).setValues([headers]);
  var headerRange = sheet.getRange(1, 1, 1, headers.length);
  headerRange.setBackground("#0f172a");
  headerRange.setFontColor("#ffffff");
  headerRange.setFontWeight("bold");
  headerRange.setHorizontalAlignment("center");
  sheet.setFrozenRows(1);
  
  // Auto-fit column widths
  for (var i = 1; i <= headers.length; i++) {
    sheet.autoResizeColumn(i);
  }
  return sheet;
}

function setupDashboard(ss) {
  if (!ss) ss = SpreadsheetApp.getActiveSpreadsheet();
  var dash = ss.getSheetByName("Analytics Dashboard");
  if (!dash) {
    dash = ss.insertSheet("Analytics Dashboard", 0);
  }
  
  dash.clear();
  dash.setTabColor("#1a73e8");
  
  // 1. Header Banner
  dash.getRange("A1:K2").merge();
  var title = dash.getRange("A1");
  title.setValue("🎯 SX BET QUANTITATIVE ENGINE — WIN/LOSS & RISK ANALYTICS");
  title.setBackground("#0f172a");
  title.setFontColor("#38bdf8");
  title.setFontSize(15);
  title.setFontWeight("bold");
  title.setHorizontalAlignment("center");
  title.setVerticalAlignment("middle");
  
  // 2. Executive KPI Cards (Row 4 to 5)
  // Card 1: Total Net PnL
  dash.getRange("B4").setValue("NET PNL ($ USDC)").setFontSize(9).setFontColor("#64748b").setFontWeight("bold");
  dash.getRange("B5").setFormula('=SUM(Trades!O2:O)').setFontSize(16).setFontWeight("bold").setNumberFormat("$#,##0.00;[Red]-$#,##0.00;$0.00");
  dash.getRange("B4:C5").setBackground("#f8fafc").setBorder(true, true, true, true, false, false, "#cbd5e1", SpreadsheetApp.BorderStyle.SOLID);
  
  // Card 2: Overall ROI
  dash.getRange("D4").setValue("OVERALL ROI (%)").setFontSize(9).setFontColor("#64748b").setFontWeight("bold");
  dash.getRange("D5").setFormula('=IF(SUM(Trades!L2:L)>0, SUM(Trades!O2:O)/SUM(Trades!L2:L), 0)').setFontSize(16).setFontWeight("bold").setNumberFormat("+0.00%;-0.00%;0.00%");
  dash.getRange("D4:E5").setBackground("#f8fafc").setBorder(true, true, true, true, false, false, "#cbd5e1", SpreadsheetApp.BorderStyle.SOLID);
  
  // Card 3: Win Rate
  dash.getRange("F4").setValue("WIN RATE (W / L)").setFontSize(9).setFontColor("#64748b").setFontWeight("bold");
  dash.getRange("F5").setFormula('=IF((COUNTIF(Trades!N2:N, "WON")+COUNTIF(Trades!N2:N, "LOST"))>0, COUNTIF(Trades!N2:N, "WON")/(COUNTIF(Trades!N2:N, "WON")+COUNTIF(Trades!N2:N, "LOST")), 0)').setFontSize(16).setFontWeight("bold").setNumberFormat("0.0%");
  dash.getRange("F4:G5").setBackground("#f8fafc").setBorder(true, true, true, true, false, false, "#cbd5e1", SpreadsheetApp.BorderStyle.SOLID);
  
  // Card 4: Avg CLV (Closing Edge)
  dash.getRange("H4").setValue("AVG CLOSING LINE VALUE").setFontSize(9).setFontColor("#64748b").setFontWeight("bold");
  dash.getRange("H5").setFormula('=IFERROR(AVERAGE(Trades!Q2:Q), 0)').setFontSize(16).setFontWeight("bold").setNumberFormat("+0.00%;-0.00%;0.00%");
  dash.getRange("H4:I5").setBackground("#f8fafc").setBorder(true, true, true, true, false, false, "#cbd5e1", SpreadsheetApp.BorderStyle.SOLID);
  
  // Card 5: Trade Volume & Breakdown
  dash.getRange("J4").setValue("SETTLED TRADES (W-L-V)").setFontSize(9).setFontColor("#64748b").setFontWeight("bold");
  dash.getRange("J5").setFormula('=COUNTIF(Trades!M2:M, "SETTLED") & " (" & COUNTIF(Trades!N2:N, "WON") & "W - " & COUNTIF(Trades!N2:N, "LOST") & "L - " & COUNTIF(Trades!N2:N, "VOID") & "V)"').setFontSize(13).setFontWeight("bold");
  dash.getRange("J4:K5").setBackground("#f8fafc").setBorder(true, true, true, true, false, false, "#cbd5e1", SpreadsheetApp.BorderStyle.SOLID);

  // 3. Section 1: Institutional Sharpness vs Variance Matrix (Rows 7-10)
  dash.getRange("B7:G7").merge().setValue("📊 1. WIN / LOSS QUALITY MATRIX (VARIANCE VS MODEL SHARPNESS)").setFontWeight("bold").setFontColor("#1e293b").setBackground("#e2e8f0");
  
  var qHeaders = ["Trade Diagnostic", "Bets", "Staked ($)", "Net PnL ($)", "ROI (%)", "Win Rate (%)"];
  dash.getRange("B8:G8").setValues([qHeaders]).setFontWeight("bold").setBackground("#334155").setFontColor("#ffffff");
  
  dash.getRange("B9").setValue("Beat the Closing Line (+CLV)");
  dash.getRange("C9").setFormula('=COUNTIFS(Trades!M2:M, "SETTLED", Trades!Q2:Q, ">0")');
  dash.getRange("D9").setFormula('=SUMIFS(Trades!L2:L, Trades!M2:M, "SETTLED", Trades!Q2:Q, ">0")').setNumberFormat("$#,##0.00");
  dash.getRange("E9").setFormula('=SUMIFS(Trades!O2:O, Trades!M2:M, "SETTLED", Trades!Q2:Q, ">0")').setNumberFormat("$#,##0.00;[Red]-$#,##0.00;$0.00");
  dash.getRange("F9").setFormula('=IF(D9>0, E9/D9, 0)').setNumberFormat("+0.00%;-0.00%;0.00%");
  dash.getRange("G9").setFormula('=IF(C9>0, COUNTIFS(Trades!N2:N, "WON", Trades!Q2:Q, ">0")/C9, 0)').setNumberFormat("0.0%");
  
  dash.getRange("B10").setValue("Trailed Closing Line (<=0% CLV)");
  dash.getRange("C10").setFormula('=COUNTIFS(Trades!M2:M, "SETTLED", Trades!Q2:Q, "<=0")');
  dash.getRange("D10").setFormula('=SUMIFS(Trades!L2:L, Trades!M2:M, "SETTLED", Trades!Q2:Q, "<=0")').setNumberFormat("$#,##0.00");
  dash.getRange("E10").setFormula('=SUMIFS(Trades!O2:O, Trades!M2:M, "SETTLED", Trades!Q2:Q, "<=0")').setNumberFormat("$#,##0.00;[Red]-$#,##0.00;$0.00");
  dash.getRange("F10").setFormula('=IF(D10>0, E10/D10, 0)').setNumberFormat("+0.00%;-0.00%;0.00%");
  dash.getRange("G10").setFormula('=IF(C10>0, COUNTIFS(Trades!N2:N, "WON", Trades!Q2:Q, "<=0")/C10, 0)').setNumberFormat("0.0%");
  dash.getRange("B8:G10").setBorder(true, true, true, true, true, true, "#cbd5e1", SpreadsheetApp.BorderStyle.SOLID);
  
  // 4. Section 2: Performance by Sport (Rows 12-18)
  dash.getRange("B12:I12").merge().setValue("⚽ 2. PERFORMANCE & EDGE BY SPORT").setFontWeight("bold").setFontColor("#1e293b").setBackground("#e2e8f0");
  var sportHeaders = ["Sport", "Settled Bets", "Wins", "Losses", "Win Rate (%)", "Total Staked ($)", "Net PnL ($)", "ROI (%)"];
  dash.getRange("B13:I13").setValues([sportHeaders]).setFontWeight("bold").setBackground("#334155").setFontColor("#ffffff");
  
  var sports = ["SOCCER", "BASKETBALL", "AMERICAN_FOOTBALL", "TENNIS", "SYSTEM"];
  for (var s = 0; s < sports.length; s++) {
    var r = 14 + s;
    var sp = sports[s];
    dash.getRange("B" + r).setValue(sp);
    dash.getRange("C" + r).setFormula('=COUNTIFS(Trades!C2:C, "' + sp + '", Trades!M2:M, "SETTLED")');
    dash.getRange("D" + r).setFormula('=COUNTIFS(Trades!C2:C, "' + sp + '", Trades!N2:N, "WON")');
    dash.getRange("E" + r).setFormula('=COUNTIFS(Trades!C2:C, "' + sp + '", Trades!N2:N, "LOST")');
    dash.getRange("F" + r).setFormula('=IF((D' + r + '+E' + r + ')>0, D' + r + '/(D' + r + '+E' + r + '), 0)').setNumberFormat("0.0%");
    dash.getRange("G" + r).setFormula('=SUMIFS(Trades!L2:L, Trades!C2:C, "' + sp + '", Trades!M2:M, "SETTLED")').setNumberFormat("$#,##0.00");
    dash.getRange("H" + r).setFormula('=SUMIFS(Trades!O2:O, Trades!C2:C, "' + sp + '", Trades!M2:M, "SETTLED")').setNumberFormat("$#,##0.00;[Red]-$#,##0.00;$0.00");
    dash.getRange("I" + r).setFormula('=IF(G' + r + '>0, H' + r + '/G' + r + ', 0)').setNumberFormat("+0.00%;-0.00%;0.00%");
  }
  dash.getRange("B13:I18").setBorder(true, true, true, true, true, true, "#cbd5e1", SpreadsheetApp.BorderStyle.SOLID);

  // 5. Section 3: Odds Bracket Performance (Rows 20-25)
  dash.getRange("B20:H20").merge().setValue("🎯 3. ODDS RANGE & CALIBRATION ANALYSIS").setFontWeight("bold").setFontColor("#1e293b").setBackground("#e2e8f0");
  var oddsHeaders = ["Odds Bracket", "Bets", "Wins", "Losses", "Win Rate (%)", "Net PnL ($)", "ROI (%)"];
  dash.getRange("B21:H21").setValues([oddsHeaders]).setFontWeight("bold").setBackground("#334155").setFontColor("#ffffff");
  
  var oddsTiers = [
    { label: "Short Favorites (1.20 - 1.50)", low: "1.20", high: "1.50" },
    { label: "Standard Favorites (1.50 - 1.90)", low: "1.50", high: "1.90" },
    { label: "Even Money (1.90 - 2.40)", low: "1.90", high: "2.40" },
    { label: "Underdogs (> 2.40)", low: "2.40", high: "99.00" }
  ];
  for (var ot = 0; ot < oddsTiers.length; ot++) {
    var rowIdx = 22 + ot;
    var tier = oddsTiers[ot];
    dash.getRange("B" + rowIdx).setValue(tier.label);
    dash.getRange("C" + rowIdx).setFormula('=COUNTIFS(Trades!M2:M, "SETTLED", Trades!G2:G, ">=' + tier.low + '", Trades!G2:G, "<' + tier.high + '")');
    dash.getRange("D" + rowIdx).setFormula('=COUNTIFS(Trades!N2:N, "WON", Trades!G2:G, ">=' + tier.low + '", Trades!G2:G, "<' + tier.high + '")');
    dash.getRange("E" + rowIdx).setFormula('=COUNTIFS(Trades!N2:N, "LOST", Trades!G2:G, ">=' + tier.low + '", Trades!G2:G, "<' + tier.high + '")');
    dash.getRange("F" + rowIdx).setFormula('=IF((D' + rowIdx + '+E' + rowIdx + ')>0, D' + rowIdx + '/(D' + rowIdx + '+E' + rowIdx + '), 0)').setNumberFormat("0.0%");
    dash.getRange("G" + rowIdx).setFormula('=SUMIFS(Trades!O2:O, Trades!M2:M, "SETTLED", Trades!G2:G, ">=' + tier.low + '", Trades!G2:G, "<' + tier.high + '")').setNumberFormat("$#,##0.00;[Red]-$#,##0.00;$0.00");
    dash.getRange("H" + rowIdx).setFormula('=IF(SUMIFS(Trades!L2:L, Trades!M2:M, "SETTLED", Trades!G2:G, ">=' + tier.low + '", Trades!G2:G, "<' + tier.high + '")>0, G' + rowIdx + '/SUMIFS(Trades!L2:L, Trades!M2:M, "SETTLED", Trades!G2:G, ">=' + tier.low + '", Trades!G2:G, "<' + tier.high + '"), 0)').setNumberFormat("+0.00%;-0.00%;0.00%");
  }
  dash.getRange("B21:H25").setBorder(true, true, true, true, true, true, "#cbd5e1", SpreadsheetApp.BorderStyle.SOLID);

  // Auto-fit dashboard columns
  dash.autoResizeColumns(1, 12);
  return dash;
}

function onOpen() {
  var ui = SpreadsheetApp.getUi();
  ui.createMenu("🚀 SX Bet Engine")
    .addItem("📊 Rebuild Analytics Dashboard", "setupAll")
    .addItem("🔄 Format Trades Sheet Only", "setupTradesSheet")
    .addToUi();
}

function doPost(e) {
  var lock = LockService.getScriptLock();
  lock.tryLock(10000);
  
  try {
    var ss = SpreadsheetApp.getActiveSpreadsheet();
    var sheet = ss.getSheetByName("Trades");
    if (!sheet) {
      sheet = setupTradesSheet(ss);
    }
    
    var data = JSON.parse(e.postData.contents);
    var action = data.action;
    
    if (action === "setup") {
      setupAll();
      return ContentService.createTextOutput(JSON.stringify({ status: "success", message: "Setup completed." }))
        .setMimeType(ContentService.MimeType.JSON);
    }
    
    if (action === "open") {
      var timestamp = Utilities.formatDate(new Date(), "GMT", "yyyy-MM-dd HH:mm:ss");
      var nextRow = sheet.getLastRow() + 1;
      
      // Dynamic Formulas for the new row
      var clvFormula = '=IF(ISBLANK(P' + nextRow + '), "", IF(P' + nextRow + '>0, (G' + nextRow + '/P' + nextRow + ' - 1), ""))';
      var roiFormula = '=IF(L' + nextRow + '>0, O' + nextRow + '/L' + nextRow + ', 0)';
      var diagnosticFormula = '=IF(N' + nextRow + '="WON", IF(Q' + nextRow + '>0, "✅ Sharp Win (+CLV)", "⚠️ Lucky Win (-CLV)"), IF(N' + nextRow + '="LOST", IF(Q' + nextRow + '>0, "🛡️ Variance Loss (+CLV)", "❌ Inefficient (-CLV)"), IF(N' + nextRow + '="VOID", "🔄 Void / Push", "⏳ Active Position")))';
      
      var newRow = [
        timestamp,                              // Col A (1)
        data.order_id || "",                    // Col B (2)
        (data.sport || "SOCCER").toUpperCase(), // Col C (3)
        data.event_name || "",                  // Col D (4)
        data.market_type || "TOTALS",           // Col E (5)
        data.outcome_name || "",                // Col F (6)
        data.decimal_odds || 0.0,               // Col G (7)
        data.model_prob || "",                  // Col H (8)
        data.market_prob || "",                 // Col I (9)
        data.edge_pct || "",                    // Col J (10)
        data.strategy_tag || "MultiSportEV",    // Col K (11)
        data.stake_usdc || 1.0,                 // Col L (12)
        "OPEN",                                 // Col M (13)
        "PENDING",                              // Col N (14)
        0.00,                                   // Col O (15) Net PnL
        "",                                     // Col P (16) Closing Odds
        clvFormula,                             // Col Q (17) CLV Formula
        roiFormula,                             // Col R (18) ROI Formula
        data.bankroll || 0.0,                   // Col S (19) Bankroll
        diagnosticFormula,                      // Col T (20) Engine Diagnostic Formula
        data.notes || ""                        // Col U (21) Qualitative Notes
      ];
      
      sheet.appendRow(newRow);
      var lastRow = sheet.getLastRow();
      
      // Apply clean formatting
      sheet.getRange(lastRow, 1, 1, newRow.length).setBackground("#f8fafc");
      sheet.getRange(lastRow, 7).setNumberFormat("0.00");         // Odds
      sheet.getRange(lastRow, 12).setNumberFormat("$#,##0.00");    // Stake
      sheet.getRange(lastRow, 15).setNumberFormat("$#,##0.00");    // PnL
      sheet.getRange(lastRow, 17).setNumberFormat("+0.00%;-0.00%"); // CLV
      sheet.getRange(lastRow, 18).setNumberFormat("+0.00%;-0.00%"); // ROI
      sheet.getRange(lastRow, 19).setNumberFormat("$#,##0.00");    // Bankroll
      
    } else if (action === "settle") {
      var orderId = data.order_id;
      var lastRow = sheet.getLastRow();
      if (lastRow > 1) {
        var idRange = sheet.getRange(2, 2, lastRow - 1, 1).getValues();
        for (var i = 0; i < idRange.length; i++) {
          if (idRange[i][0] === orderId) {
            var rowIndex = i + 2;
            sheet.getRange(rowIndex, 13).setValue("SETTLED");
            sheet.getRange(rowIndex, 14).setValue(data.result);
            sheet.getRange(rowIndex, 15).setValue(data.pnl_usdc);
            if (data.closing_odds) {
              sheet.getRange(rowIndex, 16).setValue(data.closing_odds);
            }
            if (data.bankroll) {
              sheet.getRange(rowIndex, 19).setValue(data.bankroll);
            }
            
            // Dynamic Institutional Color Coding
            if (data.result === "WON") {
              sheet.getRange(rowIndex, 1, 1, 21).setBackground("#e6f4ea"); // Soft Green
            } else if (data.result === "LOST") {
              sheet.getRange(rowIndex, 1, 1, 21).setBackground("#fce8e6"); // Soft Red
            } else {
              sheet.getRange(rowIndex, 1, 1, 21).setBackground("#fff8e1"); // Soft Yellow (VOID)
            }
            break;
          }
        }
      }
    }
    
    return ContentService.createTextOutput(JSON.stringify({ status: "success" }))
      .setMimeType(ContentService.MimeType.JSON);
      
  } catch (error) {
    return ContentService.createTextOutput(JSON.stringify({ status: "error", message: error.toString() }))
      .setMimeType(ContentService.MimeType.JSON);
  } finally {
    lock.releaseLock();
  }
}
