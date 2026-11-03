/** A file from an OS drop, plus the directory it should land in ("" = drop target). */
export type DroppedFile = {
  file: File
  dir: string
}

export type DroppedTree = {
  files: DroppedFile[]
  dirs: string[]
}

const MAX_ENTRIES = 8000

function addDir(dirs: Set<string>, rel: string) {
  const parts = rel
    .replace(/\\/g, '/')
    .split('/')
    .filter((part) => part && part !== '.' && part !== '..')
  for (let i = 1; i <= parts.length; i += 1) dirs.add(parts.slice(0, i).join('/'))
}

function fileOf(entry: FileSystemFileEntry): Promise<File> {
  return new Promise((resolve, reject) => {
    entry.file(resolve, () => reject(new Error(`Cannot read “${entry.name}”`)))
  })
}

/** readEntries returns at most 100 names; keep calling until the batch is empty. */
function readAll(reader: FileSystemDirectoryReader): Promise<FileSystemEntry[]> {
  return new Promise((resolve, reject) => {
    const all: FileSystemEntry[] = []
    const pump = () => {
      reader.readEntries((batch) => {
        if (!batch.length) {
          resolve(all)
          return
        }
        all.push(...batch)
        if (all.length > MAX_ENTRIES) {
          reject(new Error('This folder has too many items to upload at once'))
          return
        }
        pump()
      }, () => reject(new Error('Cannot read the dropped folder')))
    }
    pump()
  })
}

async function walk(entry: FileSystemEntry, prefix: string, files: DroppedFile[], dirs: Set<string>) {
  if (!entry.name || entry.name === '.' || entry.name === '..') return
  if (files.length + dirs.size > MAX_ENTRIES) {
    throw new Error('This folder has too many items to upload at once')
  }
  if (entry.isFile) {
    files.push({ file: await fileOf(entry as FileSystemFileEntry), dir: prefix })
    return
  }
  if (!entry.isDirectory) return
  const rel = prefix ? `${prefix}/${entry.name}` : entry.name
  addDir(dirs, rel)
  const children = await readAll((entry as FileSystemDirectoryEntry).createReader())
  for (const child of children) await walk(child, rel, files, dirs)
}

async function canReadFile(file: File): Promise<boolean> {
  try {
    await file.slice(0, 1).arrayBuffer()
    return true
  } catch {
    return false
  }
}

function fromRelative(file: File, dirs: Set<string>): DroppedFile {
  const rel = (file.webkitRelativePath || '').replace(/\\/g, '/')
  const slash = rel.lastIndexOf('/')
  if (slash <= 0) return { file, dir: '' }
  const dir = rel.slice(0, slash)
  addDir(dirs, dir)
  return { file, dir }
}

/**
 * Expand a desktop drop into files and folders.
 * A dropped directory is not a readable File — posting it makes fetch fail with "Failed to fetch".
 * Call this during the drop event so webkitGetAsEntry still works.
 */
export async function collectDroppedTree(transfer: DataTransfer): Promise<DroppedTree> {
  const entries: FileSystemEntry[] = []
  const items = transfer.items
  if (items) {
    for (let i = 0; i < items.length; i += 1) {
      const entry = items[i].webkitGetAsEntry?.() ?? null
      if (entry) entries.push(entry)
    }
  }
  const files: DroppedFile[] = []
  const dirs = new Set<string>()
  if (entries.length) {
    for (const entry of entries) await walk(entry, '', files, dirs)
    return { files, dirs: [...dirs] }
  }

  const plain = Array.from(transfer.files || [])
  let skippedDirectory = false
  for (const file of plain) {
    if (!(await canReadFile(file))) {
      skippedDirectory = true
      continue
    }
    files.push(fromRelative(file, dirs))
  }
  if (!files.length && skippedDirectory) throw new Error('Could not read the dropped folder')
  return { files, dirs: [...dirs] }
}

export function treeFromFileList(list: File[]): DroppedTree {
  const files: DroppedFile[] = []
  const dirs = new Set<string>()
  for (const file of list) files.push(fromRelative(file, dirs))
  return { files, dirs: [...dirs] }
}
