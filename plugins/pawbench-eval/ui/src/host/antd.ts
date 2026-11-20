/**
 * The antd surface this dashboard uses, named one by one.
 *
 * Destructured rather than re-exporting the whole namespace so a component that
 * needs something new has to add it here — the import list then doubles as the
 * inventory of what this page depends on from the host build.
 */

const antd = window.QwenPaw?.host?.antd as Record<string, any>;

export const Alert = antd.Alert;
export const App = antd.App;
export const Button = antd.Button;
export const ConfigProvider = antd.ConfigProvider;
export const DatePicker = antd.DatePicker;
export const Drawer = antd.Drawer;
export const Empty = antd.Empty;
export const Form = antd.Form;
export const Input = antd.Input;
export const InputNumber = antd.InputNumber;
export const Modal = antd.Modal;
export const Pagination = antd.Pagination;
export const Popconfirm = antd.Popconfirm;
export const Progress = antd.Progress;
export const Radio = antd.Radio;
export const Segmented = antd.Segmented;
export const Select = antd.Select;
export const Skeleton = antd.Skeleton;
export const Space = antd.Space;
export const Spin = antd.Spin;
export const Switch = antd.Switch;
export const Table = antd.Table;
export const Tabs = antd.Tabs;
export const Tag = antd.Tag;
export const Tooltip = antd.Tooltip;
export const Typography = antd.Typography;
export const Upload = antd.Upload;
export const message = antd.message;
export const theme = antd.theme;

export const Text = Typography.Text;
export const Title = Typography.Title;
export const Paragraph = Typography.Paragraph;
