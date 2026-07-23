/** Shared Ant Design Table pagination defaults (uncontrolled pageSize). */
export const TABLE_PAGE_SIZE_OPTIONS = ['10', '25', '50', '100'] as const

export function tablePagination(
  defaultPageSize = 25,
  extra?: Record<string, unknown>,
) {
  return {
    defaultPageSize,
    showSizeChanger: true,
    pageSizeOptions: [...TABLE_PAGE_SIZE_OPTIONS],
    showTotal: (total: number, range: [number, number]) =>
      `${range[0]}–${range[1]} of ${total}`,
    ...extra,
  }
}
