import type { Cell, CellWithRowAndCol, Sheet } from '@fortune-sheet/core';
import type { OperationResult, SingleRange, SpreadsheetHandle } from '../types';

export interface SpreadsheetAdapter {
  getData(): Sheet[] | null;
  setData(sheets: Sheet[] | null, activeSheetId?: string): void;
  getSelection(): SingleRange | null;
  insertText(text: string): OperationResult;
  /** Report whether a table insertion would overwrite existing cells. */
  planTable(rows: string[][]): OperationResult;
  insertTable(rows: string[][]): OperationResult;
}

const COLUMN_LETTERS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ';

export function columnLabel(index: number): string {
  let value = Math.max(0, Math.floor(index));
  let label = '';
  do {
    label = COLUMN_LETTERS[value % 26] + label;
    value = Math.floor(value / 26) - 1;
  } while (value >= 0);
  return label;
}

function normalizeRows(rows: string[][]): string[][] | null {
  if (!Array.isArray(rows) || rows.length === 0) {
    return null;
  }
  const width = rows.reduce((max, row) => Math.max(max, Array.isArray(row) ? row.length : 0), 0);
  if (width < 1) {
    return null;
  }
  return rows.map((row) => {
    const cells = Array.isArray(row) ? row.map((cell) => (cell === null || cell === undefined ? '' : String(cell))) : [];
    while (cells.length < width) {
      cells.push('');
    }
    return cells;
  });
}

function cellHasContent(cell: Cell | null | undefined): boolean {
  if (!cell) {
    return false;
  }
  const value = cell.v ?? cell.m;
  return value !== undefined && value !== null && String(value).trim() !== '';
}

export function createSpreadsheetAdapter(getHandle: () => SpreadsheetHandle | null): SpreadsheetAdapter {
  const getWorkbook = () => getHandle()?.getWorkbook() ?? null;

  const pickAnchor = (): { row: number; column: number } => {
    const workbook = getWorkbook();
    if (!workbook) {
      return { row: 0, column: 0 };
    }
    try {
      const selection = workbook.getSelection();
      const first = selection && selection.length ? selection[0] : null;
      if (first && Array.isArray(first.row) && Array.isArray(first.column)) {
        const row = Math.max(0, first.row[0] ?? 0);
        const column = Math.max(0, first.column[0] ?? 0);
        return { row, column };
      }
    } catch (error) {
      console.warn('[spreadsheetAdapter] 選択範囲を取得できませんでした', error);
    }
    return { row: 0, column: 0 };
  };

  const readCellValue = (row: number, column: number): string => {
    const workbook = getWorkbook();
    if (!workbook) {
      return '';
    }
    try {
      const value = workbook.getCellValue(row, column, { type: 'v' });
      if (value === null || value === undefined) {
        return '';
      }
      return String(value);
    } catch (error) {
      console.warn('[spreadsheetAdapter] セルを読み取れませんでした', error);
      return '';
    }
  };

  const countFilled = (target: SingleRange): number => {
    const workbook = getWorkbook();
    if (!workbook) {
      return 0;
    }
    try {
      const cells = workbook.getCellsByRange({
        row: target.row,
        column: target.column,
        row_focus: target.row[0],
        column_focus: target.column[0],
      });
      if (!Array.isArray(cells)) {
        return 0;
      }
      let filled = 0;
      for (const row of cells) {
        if (!Array.isArray(row)) {
          continue;
        }
        for (const cell of row) {
          if (cellHasContent(cell)) {
            filled += 1;
          }
        }
      }
      return filled;
    } catch (error) {
      console.warn('[spreadsheetAdapter] セル範囲を確認できませんでした', error);
      return 0;
    }
  };

  const buildTarget = (anchor: { row: number; column: number }, rowCount: number, columnCount: number): SingleRange => ({
    row: [anchor.row, anchor.row + rowCount - 1],
    column: [anchor.column, anchor.column + columnCount - 1],
  });

  return {
    getData: () => {
      const workbook = getWorkbook();
      if (!workbook) {
        return null;
      }
      try {
        return workbook.getAllSheets().map((sheet) => {
          const copy: Sheet = { ...sheet };
          const matrix = sheet.data;
          let celldata: CellWithRowAndCol[] = Array.isArray(sheet.celldata) ? sheet.celldata : [];
          if (Array.isArray(matrix) && matrix.length) {
            try {
              celldata = workbook.dataToCelldata(matrix);
            } catch (error) {
              console.warn('[spreadsheetAdapter] セルデータを変換できませんでした', error);
            }
          }
          delete (copy as { data?: unknown }).data;
          copy.celldata = celldata;
          return copy;
        });
      } catch (error) {
        console.warn('[spreadsheetAdapter] シートを取得できませんでした', error);
        return null;
      }
    },

    setData: (sheets, activeSheetId) => {
      getHandle()?.setSheets(sheets && sheets.length ? sheets : [], activeSheetId);
    },

    getSelection: () => {
      const workbook = getWorkbook();
      if (!workbook) {
        return null;
      }
      try {
        const selection = workbook.getSelection();
        const first = selection && selection.length ? selection[0] : null;
        if (first && Array.isArray(first.row) && Array.isArray(first.column)) {
          return {
            row: [first.row[0] ?? 0, first.row[1] ?? first.row[0] ?? 0],
            column: [first.column[0] ?? 0, first.column[1] ?? first.column[0] ?? 0],
          };
        }
      } catch (error) {
        console.warn('[spreadsheetAdapter] 選択範囲を取得できませんでした', error);
      }
      return null;
    },

    insertText: (text) => {
      const workbook = getWorkbook();
      if (!workbook) {
        return { ok: false, error: 'スプレッドシートが初期化されていません。' };
      }
      const anchor = pickAnchor();
      const existing = readCellValue(anchor.row, anchor.column);
      const combined = existing.trim() ? `${existing}\n${text}` : text;
      try {
        workbook.setCellValue(anchor.row, anchor.column, combined);
        workbook.setSelection([
          { row: [anchor.row, anchor.row], column: [anchor.column, anchor.column] },
        ]);
        workbook.scroll({ targetRow: anchor.row, targetColumn: anchor.column });
      } catch (error) {
        return {
          ok: false,
          error: `セルへ挿入できませんでした: ${error instanceof Error ? error.message : String(error)}`,
        };
      }
      return {
        ok: true,
        message: `セル ${columnLabel(anchor.column)}${anchor.row + 1} に挿入しました`,
      };
    },

    planTable: (rows) => {
      const normalized = normalizeRows(rows);
      if (!normalized) {
        return { ok: false, error: '表のデータが空です。' };
      }
      const workbook = getWorkbook();
      if (!workbook) {
        return { ok: false, error: 'スプレッドシートが初期化されていません。' };
      }
      const anchor = pickAnchor();
      const target = buildTarget(anchor, normalized.length, normalized[0].length);
      const filled = countFilled(target);
      const rangeLabel = `${columnLabel(target.column[0])}${target.row[0] + 1}:${columnLabel(target.column[1])}${target.row[1] + 1}`;
      return {
        ok: true,
        needsConfirm: filled > 0,
        rows: normalized.length,
        columns: normalized[0].length,
        message:
          filled > 0
            ? `${rangeLabel} に既存のデータが ${filled} セルあります。上書きしてよろしいですか？`
            : `${rangeLabel} に ${normalized.length} 行 × ${normalized[0].length} 列の表を挿入します。`,
      };
    },

    insertTable: (rows) => {
      const normalized = normalizeRows(rows);
      if (!normalized) {
        return { ok: false, error: '表のデータが空です。' };
      }
      const workbook = getWorkbook();
      if (!workbook) {
        return { ok: false, error: 'スプレッドシートが初期化されていません。' };
      }
      const anchor = pickAnchor();
      const target = buildTarget(anchor, normalized.length, normalized[0].length);
      try {
        workbook.setCellValuesByRange(normalized, target);
        if (normalized.length > 1) {
          workbook.setCellFormatByRange('bl', 1, {
            row: [anchor.row, anchor.row],
            column: [anchor.column, anchor.column + normalized[0].length - 1],
          });
          workbook.setCellFormatByRange('bg', '#EEF3FB', {
            row: [anchor.row, anchor.row],
            column: [anchor.column, anchor.column + normalized[0].length - 1],
          });
        }
        workbook.setSelection([{ row: target.row, column: target.column }]);
        workbook.scroll({ targetRow: anchor.row, targetColumn: anchor.column });
      } catch (error) {
        return {
          ok: false,
          error: `表を挿入できませんでした: ${error instanceof Error ? error.message : String(error)}`,
        };
      }
      const rangeLabel = `${columnLabel(target.column[0])}${target.row[0] + 1}:${columnLabel(target.column[1])}${target.row[1] + 1}`;
      return { ok: true, message: `${rangeLabel} に表を挿入しました` };
    },
  };
}
