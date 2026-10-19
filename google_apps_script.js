/**
 * Google Apps Script for SX Bet Quantitative Trading Bot.
 * 
 * Instructions:
 * 1. Open your Google Sheet: https://docs.google.com/spreadsheets/d/1Iay1Qc3UDpBZn7iwTi62vGBdBrBE388ehDtJLApntD8/edit
 * 2. Click "Extensions" -> "Apps Script" in the top menu.
 * 3. Delete any default code in Code.gs and paste this entire script.
 * 4. Click "Deploy" (blue button, top right) -> "New deployment".
 * 5. Select type: "Web app".
 *    - Description: "SX Bet Trade Logger"
 *    - Execute as: "Me"
 *    - Who has access: "Anyone"  <-- CRITICAL!
 * 6. Click "Deploy", approve permissions, and copy the Web App URL (ends in /exec).
 * 7. Paste that URL into your .env file:
 *    GOOGLE_SHEETS_WEBHOOK_URL=https://script.google.com/macros/s/.../exec
 */

function setupSheet() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var sheet = ss.getSheetByName("Trades");
  if (!sheet) {
    sheet = ss.insertSheet("Trades");
  }
  
  var headers = [
    "Timestamp",
    "Order ID",
    "Sport",
    "Event / Match",
    "Selection",
    "Odds",
    "Model Prob",
    "Edge (+EV)",
    "Stake ($ USDC)",
    "Status",
    "Result",
    "Net PnL ($)",
    "Bankroll ($)",
    "Closing Odds"
  ];
  
  sheet.getRange(1, 1, 1, headers.length).setValues([headers]);
  var headerRange = sheet.getRange(1, 1, 1, headers.length);
  headerRange.setBackground("#1a73e8");
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

function onOpen() {
  var ui = SpreadsheetApp.getUi();
  ui.createMenu("🚀 SX Bet Bot")
    .addItem("Initialize / Reset Headers", "setupSheet")
    .addToUi();
}

function doPost(e) {
  var lock = LockService.getScriptLock();
  lock.tryLock(10000);
  
  try {
    var sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName("Trades");
    if (!sheet) {
      sheet = setupSheet();
    }
    
    var data = JSON.parse(e.postData.contents);
    var action = data.action;
    
    if (action === "open") {
      var timestamp = Utilities.formatDate(new Date(), "GMT", "yyyy-MM-dd HH:mm:ss");
      var newRow = [
        timestamp,
        data.order_id || "",
        data.sport || "SOCCER",
        data.event_name || "",
        data.outcome_name || "",
        data.decimal_odds || "",
        data.model_prob || "",
        data.edge_pct || "",
        data.stake_usdc || 1.0,
        "OPEN",
        "PENDING",
        0.00,
        data.bankroll || "",
        ""
      ];
      sheet.appendRow(newRow);
      var lastRow = sheet.getLastRow();
      sheet.getRange(lastRow, 1, 1, newRow.length).setBackground("#f8f9fa");
      
    } else if (action === "settle") {
      var orderId = data.order_id;
      var lastRow = sheet.getLastRow();
      if (lastRow > 1) {
        var idRange = sheet.getRange(2, 2, lastRow - 1, 1).getValues();
        for (var i = 0; i < idRange.length; i++) {
          if (idRange[i][0] === orderId) {
            var rowIndex = i + 2;
            sheet.getRange(rowIndex, 10).setValue("SETTLED");
            sheet.getRange(rowIndex, 11).setValue(data.result);
            sheet.getRange(rowIndex, 12).setValue(data.pnl_usdc);
            sheet.getRange(rowIndex, 13).setValue(data.bankroll);
            if (data.closing_odds) {
              sheet.getRange(rowIndex, 14).setValue(data.closing_odds);
            }
            
            // Highlight Won / Lost
            if (data.result === "WON") {
              sheet.getRange(rowIndex, 1, 1, 14).setBackground("#e6f4ea"); // Soft green
            } else if (data.result === "LOST") {
              sheet.getRange(rowIndex, 1, 1, 14).setBackground("#fce8e6"); // Soft red
            } else {
              sheet.getRange(rowIndex, 1, 1, 14).setBackground("#fff8e1"); // Soft yellow (VOID)
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
