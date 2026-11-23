/**
 * 配置 — where the page learns where the service is.
 *
 * The token is write-only here on purpose, and the shape of the form follows
 * from that: the page is told ``has_token`` and a four-character hint, never the
 * value.  So an empty box means "keep the stored one" rather than "clear it",
 * and the ``来源`` line says where the credential came from, because "I saved
 * it" and "an environment variable set it" fail differently.
 *
 * The report defaults live in ``localStorage``: they are a reading preference,
 * not a connection fact, and moving them between machines is not something
 * anybody asked for.
 */

import { Alert, Button, Input, Segmented } from "../host/antd";
import { api, ConnectionConfig, ProbeResult, ReportFormat } from "../api";
import { describeError } from "../host/sdk";
import { useEffect, useState } from "../host/react";
import { useFeedback } from "../ui/feedback";
import { Fact, Field, Fieldset, PageHead, Panel, SectionTitle } from "../ui/primitives";

const SOURCE_TEXT: Record<string, string> = {
  file: "来自本机保存的配置",
  env: "来自环境变量（PAWBENCH_EVAL_*）",
  none: "还没有配置",
};

export function SettingsModule(props: {
  config: ConnectionConfig | null;
  onSaved: (config: ConnectionConfig) => void;
  onFormat: (value: ReportFormat) => void;
  format: ReportFormat;
}): unknown {
  const feedback = useFeedback();
  const [baseUrl, setBaseUrl] = useState("");
  const [token, setToken] = useState("");
  const [subject, setSubject] = useState("");
  const [busy, setBusy] = useState<"" | "save" | "probe">("");
  const [probe, setProbe] = useState<ProbeResult | null>(null);
  const [probeError, setProbeError] = useState("");

  useEffect(() => {
    const config = props.config;
    if (!config) return;
    setBaseUrl(config.base_url || "");
    setSubject(config.subject || "");
  }, [props.config]);

  async function save(thenProbe: boolean): Promise<void> {
    setBusy(thenProbe ? "save" : "save");
    try {
      const body: { base_url: string; subject: string; token?: string } = {
        base_url: baseUrl.trim(),
        subject: subject.trim(),
      };
      // Empty means "keep what is stored": the box never held the value.
      if (token.trim()) body.token = token.trim();
      const saved = await api.saveConfig(body);
      props.onSaved(saved);
      setToken("");
      feedback.message.success("已保存");
      if (thenProbe) await runProbe();
    } catch (err) {
      const info = describeError(err);
      feedback.message.error(`${info.code}：${info.message}`);
    } finally {
      setBusy("");
    }
  }

  async function runProbe(): Promise<void> {
    setBusy("probe");
    setProbeError("");
    try {
      const result = await api.probe();
      setProbe(result);
    } catch (err) {
      const info = describeError(err);
      setProbe(null);
      setProbeError(`${info.code}：${info.message}`);
    } finally {
      setBusy("");
    }
  }

  const config = props.config;

  return (
    <>
      <PageHead
        title="配置"
        sub="页面通过本插件后端访问评测服务，token 只在后端保存，浏览器里始终没有它。"
        actions={
          <>
            <Button onClick={runProbe} loading={busy === "probe"}>
              只探测
            </Button>
            <Button type="primary" onClick={() => void save(true)} loading={busy === "save"}>
              保存并探测
            </Button>
          </>
        }
      />

      <div className="pbe-grid">
        <Panel>
          <SectionTitle>服务连接</SectionTitle>
          <Field label="服务地址" hint="评测服务的根地址，页面会调到它下面的 /v1/*">
            <Input
              value={baseUrl}
              onChange={(event: any) => setBaseUrl(event.target.value)}
              placeholder="http://127.0.0.1:8471"
            />
          </Field>
          <Field
            label="访问 token"
            hint={
              config?.has_token
                ? `已保存 ${config.token_hint}；留空表示不改，填新值会替换`
                : "还没有 token。在服务端用 auth CLI 铸造一个，粘贴到这里。"
            }
          >
            <Input.Password
              value={token}
              onChange={(event: any) => setToken(event.target.value)}
              placeholder={config?.has_token ? "••••••••（留空不改）" : "粘贴 token"}
            />
          </Field>
          <Field label="身份" hint="服务用它判断某一行是不是你的；提交过一次后会自动学到">
            <Input
              value={subject}
              onChange={(event: any) => setSubject(event.target.value)}
              placeholder="你的 allowlist subject"
            />
          </Field>
          {probeError ? <Alert type="error" showIcon message="探测失败" description={probeError} /> : null}
        </Panel>

        <Panel>
          <SectionTitle>服务状态</SectionTitle>
          {probe ? (
            <div className="pbe-facts">
              <Fact
                label="可达"
                value={probe.reachable ? "是" : "否"}
              />
              <Fact label="被认可" value={probe.authorized ? "是" : "否"} />
              <Fact label="说明" value={String(probe.detail || "—")} />
              <Fact label="配置来源" value={SOURCE_TEXT[config?.source ?? "none"] ?? config?.source ?? "—"} />
            </div>
          ) : (
            <div className="pbe-facts">
              <Fact label="配置来源" value={SOURCE_TEXT[config?.source ?? "none"] ?? config?.source ?? "—"} />
              <Fact label="地址" value={config?.base_url || "还没填"} />
              <Fact label="token" value={config?.has_token ? `已保存 ${config.token_hint}` : "还没有"} />
              <Fact label="身份" value={config?.subject || "还没学到"} />
            </div>
          )}
          <div className="pbe-cell-sub" style={{ marginTop: "var(--spacer-16)" }}>
            探测会打服务的 /healthz：先看能不能连上，再看 token 认不认，最后报服务自己的版本。
          </div>
        </Panel>

        <Panel>
          <SectionTitle>报告默认值</SectionTitle>
          <Fieldset title="">
            <Field label="导出格式">
              <Segmented
                value={props.format}
                onChange={(value: any) => props.onFormat(value as ReportFormat)}
                options={[
                  { value: "md", label: "Markdown" },
                  { value: "html", label: "HTML" },
                  { value: "json", label: "JSON" },
                  { value: "zip", label: "ZIP" },
                ]}
              />
            </Field>
          </Fieldset>
          <div className="pbe-cell-sub">这两个只影响打开报告时的默认选择，存在这台浏览器里。</div>
        </Panel>

        <Panel>
          <SectionTitle>关于 token</SectionTitle>
          <div className="pbe-cell-sub" style={{ lineHeight: 1.8 }}>
            页面调的是 <span className="pbe-mono">/api/pawbench-eval/v1/…</span>，插件后端在转发时加上
            <span className="pbe-mono"> Authorization: Bearer …</span>。所以：
            <br />· 浏览器里没有 token 的副本，同事来屏幕共享也看不到；
            <br />· 换机器要重新填一次，因为它跟着这台机器的插件目录走；
            <br />· 轮换 token 之后，页面学到的提交人身份会作废，第一次提交时重新学。
          </div>
        </Panel>
      </div>
    </>
  );
}
