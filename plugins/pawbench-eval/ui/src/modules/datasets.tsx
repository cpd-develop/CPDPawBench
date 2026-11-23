/**
 * 数据集 — what a run can be asked to cover.
 *
 * Two kinds share the list because to a submitter they are the same thing: a
 * named set of tasks.  A *builtin view* is a saved filter over the shipped
 * corpus; a *custom package* is a zip somebody prepared.  Both participate in
 * the mixed selector identically, which is the property that makes "run these
 * twelve tasks" expressible without editing the corpus.
 *
 * A delete button appears only on rows you own — the service enforces this, and
 * showing the button anyway would be a UI that offers refusals.
 */

import { Button, Input, Modal, Popconfirm, Select, Table } from "../host/antd";
import { api, DatasetItem } from "../api";
import { describeError } from "../host/sdk";
import { useEffect, useMemo, useState } from "../host/react";
import { useFeedback } from "../ui/feedback";
import { CopyId, EmptyHint, Field, Fieldset, PageHead, Panel, stamp } from "../ui/primitives";

export function DatasetsModule(props: {
  subject: string;
  onOpen: (datasetId: string) => void;
}): unknown {
  const feedback = useFeedback();
  const [datasets, setDatasets] = useState<DatasetItem[]>([]);
  const [categories, setCategories] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [viewOpen, setViewOpen] = useState(false);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [categoryOpen, setCategoryOpen] = useState(false);
  const [search, setSearch] = useState("");

  async function load(): Promise<void> {
    setLoading(true);
    try {
      const [list, cats] = await Promise.all([api.datasets(), api.categories()]);
      setDatasets(list.datasets);
      setCategories(cats.categories.map((item) => item.name));
      setError("");
    } catch (err) {
      const info = describeError(err);
      setError(`${info.code}：${info.message}`);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  const shown = useMemo(() => {
    const needle = search.trim().toLowerCase();
    if (!needle) return datasets;
    return datasets.filter((item) =>
      [item.id, item.name, item.description, item.categories.join(" ")]
        .join(" ")
        .toLowerCase()
        .includes(needle),
    );
  }, [datasets, search]);

  async function remove(item: DatasetItem): Promise<void> {
    try {
      await api.deleteDataset(item.id);
      feedback.message.success(`已删除 ${item.id}`);
      void load();
    } catch (err) {
      const info = describeError(err);
      feedback.message.error(`${info.code}：${info.message}`);
    }
  }

  return (
    <>
      <PageHead
        title="数据集"
        sub="内置视图是筛选快照，自定义包是上传的题目集；两者在提交页里混选。"
        actions={
          <>
            <Button onClick={() => void load()} loading={loading}>
              刷新
            </Button>
            <Button onClick={() => setCategoryOpen(true)}>管理分类</Button>
            <Button onClick={() => setUploadOpen(true)}>上传任务包</Button>
            <Button type="primary" onClick={() => setViewOpen(true)}>
              新建视图
            </Button>
          </>
        }
      />

      {error ? (
        <Panel>
          <span className="pbe-cell-sub">{error}</span>
        </Panel>
      ) : null}

      <div className="pbe-toolbar">
        <span className="pbe-toolbar__label">搜索</span>
        <Input.Search
          allowClear
          aria-label="搜索数据集"
          placeholder="名称 / id / 分类 / 描述"
          style={{ width: 280 }}
          value={search}
          onChange={(event: any) => setSearch(event.target.value)}
        />
        <div className="pbe-toolbar__right">
          <span className="pbe-toolbar__label">
            共 {datasets.length} 个 · {categories.length} 个分类
          </span>
        </div>
      </div>

      <div className="pbe-table-wrap">
        <Table
          className="pbe-table"
          rowKey="id"
          size="middle"
          loading={loading}
          dataSource={shown}
          pagination={{ pageSize: 50, hideOnSinglePage: true }}
          onRow={(item: DatasetItem) => ({
            onClick: () => props.onOpen(item.id),
            // The row is the primary navigation of this page; a click-only row
            // puts it out of reach of a keyboard and of a screen reader.
            tabIndex: 0,
            onKeyDown: (event: any) => {
              // A button inside the row owns its own Enter/Space: opening the
              // dataset when somebody activates 删除 would be a surprise.
              if (event.target !== event.currentTarget) return;
              if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                props.onOpen(item.id);
              }
            },
          })}
          locale={{ emptyText: <EmptyHint>还没有数据集。可以上传一个任务包，或从内置语料里切一个视图。</EmptyHint> }}
          columns={[
            {
              title: "名称",
              dataIndex: "name",
              render: (_: unknown, item: DatasetItem) => (
                <div>
                  <div className="pbe-cell-title">{item.name || item.id}</div>
                  <div className="pbe-cell-sub">{item.description || item.id}</div>
                </div>
              ),
            },
            {
              title: "类型",
              dataIndex: "kind",
              width: 130,
              render: (value: string) => (
                <span className="pbe-cell-sub">
                  {value === "builtin_view" ? "内置视图" : value === "custom_package" ? "自定义包" : value}
                </span>
              ),
            },
            {
              title: "分类",
              dataIndex: "categories",
              width: 200,
              render: (value: string[]) => (
                <span className="pbe-cell-sub">{(value ?? []).join("、") || "—"}</span>
              ),
            },
            {
              title: "题量",
              dataIndex: "task_count",
              width: 80,
              render: (value: number) => <span className="pbe-mono">{value}</span>,
            },
            {
              title: "负责人",
              dataIndex: "owner",
              width: 110,
              render: (value: string) => <span className="pbe-cell-sub">{value}</span>,
            },
            {
              title: "更新",
              dataIndex: "updated_at",
              width: 150,
              render: (value: string) => <span className="pbe-cell-sub">{stamp(value)}</span>,
            },
            {
              title: "操作",
              dataIndex: "id",
              width: 130,
              render: (_: unknown, item: DatasetItem) =>
                props.subject && item.owner === props.subject ? (
                  // The cell stops the click: the row opens the dataset, and a
                  // delete that also navigated would be a page change nobody
                  // asked for behind a confirmation.
                  <div onClick={(event: any) => event.stopPropagation()}>
                    <Popconfirm
                      title="删除这个数据集？"
                      description="已经被作业引用过的数据集可能删不掉。"
                      okText="删除"
                      cancelText="不删"
                      onConfirm={() => remove(item)}
                    >
                      <Button size="small" type="text" danger>
                        删除
                      </Button>
                    </Popconfirm>
                  </div>
                ) : (
                  <span className="pbe-cell-sub">只读</span>
                ),
            },
          ]}
        />
        <div className="pbe-table__foot">
          <span>共 {shown.length} 条</span>
          <span>点一行看题目清单；删除只对自己创建的行开放</span>
        </div>
      </div>

      <CreateViewModal
        open={viewOpen}
        categories={categories}
        onClose={() => setViewOpen(false)}
        onDone={() => {
          setViewOpen(false);
          void load();
        }}
      />
      <UploadModal
        open={uploadOpen}
        categories={categories}
        onClose={() => setUploadOpen(false)}
        onDone={() => {
          setUploadOpen(false);
          void load();
        }}
      />
      <CategoryModal
        open={categoryOpen}
        categories={categories}
        onClose={() => setCategoryOpen(false)}
        onDone={() => void load()}
      />
    </>
  );
}

function CreateViewModal(props: {
  open: boolean;
  categories: string[];
  onClose: () => void;
  onDone: () => void;
}): unknown {
  const feedback = useFeedback();
  const [id, setId] = useState("");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [scenario, setScenario] = useState("");
  const [capability, setCapability] = useState("");
  const [complexity, setComplexity] = useState("");
  const [filed, setFiled] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);

  async function submit(): Promise<void> {
    const filter: Record<string, unknown> = {};
    if (scenario.trim()) filter.scenario = scenario.trim();
    if (capability.trim()) {
      filter.capability = capability
        .split(",")
        .map((item) => item.trim())
        .filter(Boolean);
    }
    if (complexity.trim()) filter.complexity = complexity.trim();
    if (!Object.keys(filter).length) {
      feedback.message.error("至少要填一个筛选条件，否则等于整个语料");
      return;
    }
    setBusy(true);
    try {
      await api.createDataset({
        id: id.trim(),
        name: name.trim() || id.trim(),
        description: description.trim(),
        filter,
        categories: filed,
      });
      feedback.message.success("视图已保存");
      setId("");
      setName("");
      setDescription("");
      setScenario("");
      setCapability("");
      setComplexity("");
      setFiled([]);
      props.onDone();
    } catch (err) {
      const info = describeError(err);
      feedback.message.error(`${info.code}：${info.message}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      open={props.open}
      title="新建内置视图"
      width={620}
      onCancel={props.onClose}
      onOk={submit}
      okText="保存视图"
      cancelText="取消"
      confirmLoading={busy}
    >
      <Fieldset title="标识">
        <Field label="id" hint="小写字母、数字与下划线，保存后不可改">
          <Input value={id} onChange={(event: any) => setId(event.target.value)} placeholder="如 regression_smoke" />
        </Field>
        <Field label="名称">
          <Input value={name} onChange={(event: any) => setName(event.target.value)} placeholder="给人看的名字" />
        </Field>
        <Field label="描述">
          <Input value={description} onChange={(event: any) => setDescription(event.target.value)} />
        </Field>
      </Fieldset>

      <Fieldset title="筛选（至少要有一项）">
        <Field label="场景" hint="如 Software_Engineering/Code，留空表示不限">
          <Input value={scenario} onChange={(event: any) => setScenario(event.target.value)} />
        </Field>
        <Field label="能力" hint="多个用英文逗号分隔">
          <Input value={capability} onChange={(event: any) => setCapability(event.target.value)} />
        </Field>
        <Field label="复杂度" hint="L1 / L2 / L3">
          <Input value={complexity} onChange={(event: any) => setComplexity(event.target.value)} />
        </Field>
      </Fieldset>

      <Field label="分类">
        <Select
          mode="tags"
          style={{ width: "100%" }}
          value={filed}
          onChange={(value: any) => setFiled(value)}
          options={props.categories.map((name) => ({ value: name, label: name }))}
          placeholder="选已有分类，或直接输入新名字"
        />
      </Field>
    </Modal>
  );
}

function UploadModal(props: {
  open: boolean;
  categories: string[];
  onClose: () => void;
  onDone: () => void;
}): unknown {
  const feedback = useFeedback();
  const [id, setId] = useState("");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [filed, setFiled] = useState<string[]>([]);
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(): Promise<void> {
    if (!file) {
      feedback.message.error("先选一个 zip 任务包");
      return;
    }
    const query = new URLSearchParams();
    query.set("id", id.trim());
    query.set("name", name.trim() || id.trim());
    query.set("description", description.trim());
    for (const category of filed) query.append("categories", category);
    setBusy(true);
    try {
      await api.uploadPackage(file, query.toString());
      feedback.message.success("任务包已登记");
      setFile(null);
      setId("");
      setName("");
      setDescription("");
      setFiled([]);
      props.onDone();
    } catch (err) {
      const info = describeError(err);
      feedback.message.error(`${info.code}：${info.message}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      open={props.open}
      title="上传任务包"
      width={620}
      onCancel={props.onClose}
      onOk={submit}
      okText="上传并登记"
      cancelText="取消"
      confirmLoading={busy}
    >
      <Field label="zip 文件">
        <input
          type="file"
          accept=".zip"
          onChange={(event: any) => setFile(event.target.files?.[0] ?? null)}
        />
      </Field>
      <Field label="id" hint="登记后作为数据集 id，小写字母、数字与下划线">
        <Input value={id} onChange={(event: any) => setId(event.target.value)} placeholder="如 office_batch_2" />
      </Field>
      <Field label="名称">
        <Input value={name} onChange={(event: any) => setName(event.target.value)} />
      </Field>
      <Field label="描述">
        <Input value={description} onChange={(event: any) => setDescription(event.target.value)} />
      </Field>
      <Field label="分类">
        <Select
          mode="tags"
          style={{ width: "100%" }}
          value={filed}
          onChange={(value: any) => setFiled(value)}
          options={props.categories.map((value) => ({ value, label: value }))}
        />
      </Field>
    </Modal>
  );
}

function CategoryModal(props: {
  open: boolean;
  categories: string[];
  onClose: () => void;
  onDone: () => void;
}): unknown {
  const feedback = useFeedback();
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);

  async function add(): Promise<void> {
    if (!draft.trim()) return;
    setBusy(true);
    try {
      await api.createCategory({ name: draft.trim() });
      setDraft("");
      feedback.message.success("分类已创建");
      props.onDone();
    } catch (err) {
      const info = describeError(err);
      feedback.message.error(`${info.code}：${info.message}`);
    } finally {
      setBusy(false);
    }
  }

  async function remove(name: string): Promise<void> {
    try {
      await api.deleteCategory(name);
      feedback.message.success(`已删除分类 ${name}`);
      props.onDone();
    } catch (err) {
      const info = describeError(err);
      feedback.message.error(`${info.code}：${info.message}`);
    }
  }

  return (
    <Modal open={props.open} title="分类" width={520} onCancel={props.onClose} footer={<Button onClick={props.onClose}>完成</Button>}>
      <Field label="新分类" hint="分类只用来归拢数据集，选中它等于选中其下所有数据集">
        <Input.Search
          value={draft}
          onChange={(event: any) => setDraft(event.target.value)}
          onSearch={add}
          enterButton="创建"
          loading={busy}
        />
      </Field>
      <div className="pbe-rows">
        {props.categories.length ? (
          props.categories.map((name) => (
            <div className="pbe-row" key={name}>
              <span className="pbe-row__grow">
                <CopyId value={name} label="分类" keep={40} />
              </span>
              <Popconfirm title="删除这个分类？" okText="删除" cancelText="不删" onConfirm={() => remove(name)}>
                <Button size="small" type="text" danger>
                  删除
                </Button>
              </Popconfirm>
            </div>
          ))
        ) : (
          <EmptyHint>还没有分类</EmptyHint>
        )}
      </div>
    </Modal>
  );
}
