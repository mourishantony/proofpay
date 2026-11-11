import { useMemo } from "react";
import { AgGridReact } from "ag-grid-react";
import { themeQuartz } from "ag-grid-community";
import StatusPill from "./StatusPill.jsx";
import { money } from "../api.js";

export const gridTheme = themeQuartz.withParams({
  accentColor: "#0b5cff",
  fontFamily: "inherit",
  fontSize: 13,
  headerFontWeight: 600,
  headerBackgroundColor: "#f6f8fc",
  rowHoverColor: "#f0f5ff",
  selectedRowBackgroundColor: "#e6eeff",
  borderColor: "#e6e9f0",
  wrapperBorderRadius: 10,
});

function QaCell({ data }) {
  if (data.qa_score == null) return <span className="muted">-</span>;
  return <span className={`qa-chip ${data.qa_passed ? "ok" : "bad"}`}>{data.qa_score}</span>;
}

export default function MilestoneGrid({ rows, selectedId, onSelect }) {
  const columnDefs = useMemo(
    () => [
      { field: "id", headerName: "#", width: 70, sort: "desc" },
      { field: "title", headerName: "Milestone", flex: 2, minWidth: 180, filter: true },
      { field: "domain", headerName: "Type", width: 120, filter: true,
        valueFormatter: (p) => ({ steel_drawing: "Drawing", code: "Code", design: "Design", document: "Document", other: "Other" })[p.value] || p.value },
      { field: "freelancer_name", headerName: "Freelancer", flex: 1, minWidth: 120, filter: true },
      {
        field: "amount", headerName: "Amount", width: 120, type: "rightAligned",
        valueGetter: (p) => Number(p.data.amount), valueFormatter: (p) => money(p.value, p.data.currency),
      },
      { field: "status", headerName: "Status", flex: 1.4, minWidth: 190, cellRenderer: (p) => <StatusPill status={p.value} />, filter: true },
      { field: "qa_score", headerName: "QA", width: 80, cellRenderer: QaCell },
      {
        field: "updated_at", headerName: "Updated", width: 140,
        valueFormatter: (p) => (p.value ? new Date(p.value + (p.value.endsWith("Z") ? "" : "Z")).toLocaleString([], { dateStyle: "short", timeStyle: "short" }) : ""),
      },
    ],
    []
  );

  return (
    <div className="grid-wrap">
      <AgGridReact
        theme={gridTheme}
        rowData={rows}
        columnDefs={columnDefs}
        getRowId={(p) => String(p.data.id)}
        rowSelection={{ mode: "singleRow", checkboxes: false, enableClickSelection: true }}
        onRowClicked={(e) => onSelect(e.data.id)}
        rowClassRules={{ "row-active": (p) => p.data?.id === selectedId }}
        overlayNoRowsTemplate="No milestones yet - create one to start."
        domLayout="autoHeight"
        animateRows
      />
    </div>
  );
}
