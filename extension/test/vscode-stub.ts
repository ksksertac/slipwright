// Just enough of the editor's API for the pure parts of the extension to be tested here.
export class TreeItem {
  constructor(
    public label: string,
    public collapsibleState?: number,
  ) {}
}
export class ThemeIcon {
  constructor(public id: string) {}
}
export class EventEmitter<T> {
  event = (_listener: (e: T) => void): { dispose(): void } => ({ dispose() {} });
  fire(_value?: T): void {}
}
export class MarkdownString {
  constructor(public value: string) {}
}
export const TreeItemCollapsibleState = { None: 0, Collapsed: 1, Expanded: 2 };
export const window = {};
export const workspace = { getConfiguration: () => ({ get: () => undefined }) };
export const commands = {};
