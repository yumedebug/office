import { forwardRef, useCallback, useEffect, useImperativeHandle, useRef, useState } from 'react';
import { Workbook, type WorkbookInstance } from '@fortune-sheet/react';
import type { Sheet } from '@fortune-sheet/core';
import '@fortune-sheet/react/dist/index.css';
import type { SpreadsheetHandle } from '../types';

interface SpreadsheetEditorProps {
  /** Sheets restored from a project; omitted for a brand new workbook. */
  initialSheets?: Sheet[];
  onChange?: () => void;
}

const DEFAULT_SHEET: Sheet = { name: 'Sheet1' };

/**
 * FortuneSheet is used as a controlled component: ``data`` is only replaced
 * when a whole project is loaded (which also bumps ``revision``), so typing
 * inside the grid never feeds data back into the component.
 */
const SpreadsheetEditor = forwardRef<SpreadsheetHandle, SpreadsheetEditorProps>(
  function SpreadsheetEditor({ initialSheets, onChange }, ref) {
    const workbookRef = useRef<WorkbookInstance | null>(null);
    const [sheetData, setSheetData] = useState<Sheet[]>(() =>
      initialSheets && initialSheets.length ? initialSheets : [DEFAULT_SHEET],
    );
    const [revision, setRevision] = useState(0);
    /** Sheet that should be active once the remounted workbook is ready. */
    const pendingSheetRef = useRef<string | null>(null);

    const activate = useCallback((sheetId: string): boolean => {
      const workbook = workbookRef.current;
      if (!workbook || !sheetId) {
        return false;
      }
      try {
        workbook.activateSheet({ id: sheetId });
        // Put the caret on the top-left cell so the sheet is clearly "open".
        workbook.setSelection([{ row: [0, 0], column: [0, 0] }]);
        workbook.scroll({ targetRow: 0, targetColumn: 0 });
        return true;
      } catch (error) {
        console.warn('[SpreadsheetEditor] シートを切り替えられませんでした', error);
        return false;
      }
    }, []);

    useImperativeHandle(
      ref,
      () => ({
        getWorkbook: () => workbookRef.current,
        setSheets: (sheets: Sheet[], activeSheetId?: string) => {
          pendingSheetRef.current = activeSheetId ?? null;
          setSheetData(sheets && sheets.length ? sheets : [DEFAULT_SHEET]);
          setRevision((value) => value + 1);
        },
        activateSheet: (sheetId: string) => {
          if (!activate(sheetId)) {
            pendingSheetRef.current = sheetId;
          }
        },
      }),
      [activate],
    );

    // After a remount the new workbook is committed before this effect runs;
    // defer one frame so FortuneSheet has finished building its sheet tabs.
    useEffect(() => {
      const sheetId = pendingSheetRef.current;
      if (!sheetId) {
        return undefined;
      }
      pendingSheetRef.current = null;
      const timer = window.setTimeout(() => {
        activate(sheetId);
      }, 0);
      return () => window.clearTimeout(timer);
    }, [activate, revision]);

    const handleChange = useCallback(() => {
      onChange?.();
    }, [onChange]);

    return (
      <div className="sheet-host">
        <Workbook
          key={revision}
          ref={workbookRef}
          data={sheetData}
          onChange={handleChange}
          showToolbar
          showFormulaBar
          showSheetTabs
          lang="en"
        />
      </div>
    );
  },
);

export default SpreadsheetEditor;
