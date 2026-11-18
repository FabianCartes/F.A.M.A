/**
 * Classes that render one table as stacked cards below the `md` breakpoint and
 * as a regular table from `md` up. Each cell names itself through `data-label`,
 * shown as a CSS pseudo-element, so the markup, the text and the accessible
 * table roles stay identical across both layouts.
 */
export const stackedTable = "block w-full text-left md:table";

export const stackedRow =
  "block mb-3 rounded-xl border border-[#23252e] bg-[#101114]/60 p-3 " +
  "md:table-row md:mb-0 md:rounded-none md:border-0 md:bg-transparent md:p-0";

export const stackedCell =
  "flex items-start justify-between gap-3 py-1.5 text-right " +
  "before:content-[attr(data-label)] before:shrink-0 before:text-left before:text-gray-500 " +
  "md:table-cell md:text-left md:before:content-none";
