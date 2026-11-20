/**
 * 新建评测 — the submission form, in a dialog over the list.
 *
 * Three bands, in the order the questions occur to somebody: where the agent
 * is, what should be covered, and when it may run.  Two details are load
 * bearing:
 *
 * - The task count is resolved by the *service*, not counted here.  Category
 *   expansion and de-duplication live there, and a client-side guess would
 *   disagree with what actually gets queued exactly when a task sits in two
 *   selected sets.
 * - The window shows the reader's zone and the service's zone on separate
 *   lines.  A single wall-clock time is how a "nightly" run silently starts at
 *   the wrong hour for anybody in another timezone — the service resolves in
 *   its own zone, so saying it plainly is cheaper than a post-mortem.
 */

import { Alert, Button, DatePicker, Input, Modal, Select, Segmented, Spin } from "../host/antd";
import { api, CategoryList, DatasetList, JobItem, ResolveResult } from "../api";
import { describeError } from "../host/sdk";
import { useEffect, useMemo, useState } from "../host/react";
import { useFeedback } from "../ui/feedback";
import { Field, Fieldset, Figure } from "../ui/primitives";

type WindowKind = "immediate" | "night" | "custom";

export function NewJobModal(props: {
  open: boolean;
  onClose: () => void;
  onSubmitted: (job: JobItem) => void;
  onIdentity: (subject: string) => void;
}): unknown {
  const feedback = useFeedback();
  const [acpUrl, setAcpUrl] = useState("");
  const [product, setProduct] = useState("");
  const [purpose, setPurpose] = useState("");
  const [datasets, setDatasets] = useState<string[]>([]);
  const [categories, setCategories] = useState<string[]>([]);
  const [kind, setKind] = useState<WindowKind>("immediate");
  const [range, setRange] = useState<[any, any] | null>(null);
  const [catalog, setCatalog] = useState<{ datasets: DatasetList | null; categories: CategoryList | null }>({
    datasets: null,
    categories: null,
  });
  const [resolved, setResolved] = useState<ResolveResult | null>(null);
  const [resolving, setResolving] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!props.open) return;
    let alive = true;
    Promise.all([api.datasets(), api.categories()])
      .then(([list, cats]) => {
        if (alive) setCatalog({ datasets: list, categories: cats });
      })
      .catch((err) => {
        const info = describeError(err);
        feedback.message.error(`${info.code}：${info.message}`);
      });
    return () => {
      alive = false;
    };
  }, [props.open]);

  const selection = useMemo(() => ({ categories, datasets }), [categories, datasets]);

  useEffect(() => {
    if (!props.open) return;
    if (!categories.length && !datasets.length) {
      setResolved(null);
      return;
    }
    let alive = true;
    setResolving(true);
    api
      .resolve(selection)
      .then((result) => {
        if (alive) setResolved(result);
      })
      .catch(() => {
        if (alive) setResolved(null);
      })
      .finally(() => {
        if (alive) setResolving(false);
      });
    return () => {
      alive = false;
    };
  }, [categories, datasets, props.open]);

  async function submit(): Promise<void> {
    const window: Record<string, unknown> = { kind };
    if (kind === "custom") {
      if (!range || !range[0] || !range[1]) {
        feedback.message.error("自定义区间要选开始和结束时间");
        return;
      }
      window.not_before = toIso(range[0]);
      window.not_after = toIso(range[1]);
    }
    setBusy(true);
    try {
      const job = await api.submit({
        acp_url: acpUrl.trim(),
        product: product.trim(),
        purpose: purpose.trim(),
        selector: { categories, datasets },
        window: window as any,
      });
      feedback.message.success(`已提交 ${job.job_id}`);
      // Whoever submitted is the token's subject; remember it so the list can
      // offer "上移" on exactly the rows this person may touch.
      api
        .learnIdentity(job.job_id)
        .then((result) => result.subject && props.onIdentity(result.subject))
        .catch(() => undefined);
      setAcpUrl("");
      setProduct("");
      setPurpose("");
      setCategories([]);
      setDatasets([]);
      setKind("immediate");
      setRange(null);
      props.onSubmitted(job);
    } catch (err) {
      const info = describeError(err);
      feedback.message.error(`${info.code}：${info.message}`);
    } finally {
      setBusy(false);
    }
  }

  const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
  const serviceTz = "Asia/Shanghai";

  return (
    <Modal
      open={props.open}
      title="新建评测"
      width={680}
      onCancel={props.onClose}
      onOk={submit}
      okText="提交评测"
      cancelText="取消"
      confirmLoading={busy}
      destroyOnClose
      footer={
        <div style={{ display: "flex", justifyContent: "flex-end", gap: "var(--spacer-8)" }}>
          <Button onClick={props.onClose}>取消</Button>
          <Button
            type="primary"
            loading={busy}
            disabled={!acpUrl.trim() || !product.trim() || !purpose.trim()}
            onClick={submit}
          >
            提交评测
          </Button>
        </div>
      }
    >
      <Fieldset title="目标">
        <Field label="ACP 地址" hint="被测 agent 的 ACP 端点，http:// 或 https:// 开头">
          <Input
            value={acpUrl}
            onChange={(event: any) => setAcpUrl(event.target.value)}
            placeholder="http://127.0.0.1:8472/acp"
          />
        </Field>
        <Field label="产品">
          <Input
            value={product}
            onChange={(event: any) => setProduct(event.target.value)}
            placeholder="被评测的是什么，如 QwenPaw 2.3"
          />
        </Field>
        <Field label="目的" hint="一周后回看，能解释这条曲线为什么跳的就是这两栏">
          <Input
            value={purpose}
            onChange={(event: any) => setPurpose(event.target.value)}
            placeholder="如 夜间冒烟 / 回归 / 发版前"
          />
        </Field>
      </Fieldset>

      <Fieldset title="选题">
        <Field label="分类" hint="选中一个分类等于选中它下面所有数据集">
          <Select
            mode="multiple"
            allowClear
            style={{ width: "100%" }}
            value={categories}
            onChange={(value: any) => setCategories(value)}
            placeholder="按分类整组选"
            options={(catalog.categories?.categories ?? []).map((item) => ({
              value: item.name,
              label: item.name,
            }))}
          />
        </Field>
        <Field label="数据集">
          <Select
            mode="multiple"
            allowClear
            style={{ width: "100%" }}
            value={datasets}
            onChange={(value: any) => setDatasets(value)}
            placeholder="选单个数据集"
            options={(catalog.datasets?.datasets ?? []).map((item) => ({
              value: item.id,
              label: `${item.name || item.id}（${item.task_count} 题）`,
            }))}
          />
        </Field>
        <Field label="题量">
          <div className="pbe-cell-sub">
            {resolving ? (
              <Spin size="small" />
            ) : resolved ? (
              <>
                将跑 <Figure value={resolved.task_count} /> 道题
                {resolved.duplicates_removed ? ` · 去重 ${resolved.duplicates_removed} 道` : ""}
                {resolved.unknown_ids?.length ? ` · ${resolved.unknown_ids.length} 个选择项不存在` : ""}
              </>
            ) : (
              "选完分类或数据集后，这里显示服务算出来的题量"
            )}
          </div>
        </Field>
      </Fieldset>

      <Fieldset title="窗口">
        <Field label="何时跑">
          <Segmented
            value={kind}
            onChange={(value: any) => setKind(value as WindowKind)}
            options={[
              { value: "immediate", label: "立即" },
              { value: "night", label: "夜间固定窗" },
              { value: "custom", label: "自定义区间" },
            ]}
          />
        </Field>
        {kind === "custom" ? (
          <Field label="区间" hint={`按本机时区选择（${tz}）`}>
            <DatePicker.RangePicker
              showTime
              style={{ width: "100%" }}
              value={range as any}
              onChange={(value: any) => setRange(value)}
            />
          </Field>
        ) : null}
        {kind !== "immediate" ? (
          <Alert
            type="info"
            showIcon
            message={`服务在 ${serviceTz} 判断窗口`}
            description={
              kind === "night"
                ? `夜间固定窗由服务配置决定，本机时区是 ${tz}；两者不同的话，以服务为准。`
                : `你按 ${tz} 选的时间会换算成 UTC 发给服务，报告里显示的是 UTC。`
            }
          />
        ) : null}
      </Fieldset>

    </Modal>
  );
}

function toIso(value: any): string {
  if (value && typeof value.toISOString === "function") return value.toISOString();
  if (value && typeof value.toDate === "function") return value.toDate().toISOString();
  return new Date(value).toISOString();
}

