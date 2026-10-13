(function (deckyFrontendLib, React) {
  'use strict';

  const { PanelSection, PanelSectionRow, ToggleField, ButtonItem, ConfirmModal, showModal, staticClasses } = deckyFrontendLib;
  const h = React.createElement;

  function Content(props) {
    const serverAPI = props.serverAPI;
    const [status, setStatus] = React.useState(null);
    const [busy, setBusy] = React.useState(false);

    const call = (method, args) =>
      serverAPI.callPluginMethod(method, args || {}).then((r) => {
        if (r.success) return r.result;
        throw new Error(String(r.result));
      });

    const fail = (e) => setStatus((s) => Object.assign({}, s || {}, { enabled: false, hardware: null, error: e.message }));
    const refresh = () => call('get_status').then(setStatus).catch(fail);

    React.useEffect(() => { refresh(); }, []);

    const installing = !!(status && status.install && status.install.running);
    React.useEffect(() => {
      if (!installing) return undefined;
      const id = setInterval(refresh, 2000);
      return () => clearInterval(id);
    }, [installing]);

    const onToggle = (value) => {
      setBusy(true);
      call('set_limit', { enabled: value })
        .then(setStatus)
        .catch(fail)
        .then(() => setBusy(false));
    };

    const onUnlock = (value) => {
      setBusy(true);
      call('set_unlocked', { unlocked: value })
        .then(setStatus)
        .catch(fail)
        .then(() => setBusy(false));
    };

    const doInstall = () => call('start_install').then(setStatus).catch(fail);
    const onInstall = () => {
      if (typeof showModal === 'function' && ConfirmModal) {
        showModal(h(ConfirmModal, {
          strTitle: 'Install acpi_call?',
          strDescription: 'This temporarily unlocks the SteamOS system partition, installs kernel headers, build tools and the acpi_call module, then locks it again. It needs internet and takes several minutes. A SteamOS update will remove it again.',
          strOKButtonText: 'Install',
          onOK: doInstall,
        }));
      } else {
        doInstall();
      }
    };

    let hw = 'Firmware state: unknown';
    if (status && status.hardware === true) hw = 'Firmware reports: limit ON';
    if (status && status.hardware === false) hw = 'Firmware reports: limit OFF';

    const inst = status && status.install;
    const mono = { fontFamily: 'monospace', fontSize: '10px', whiteSpace: 'pre-wrap', wordBreak: 'break-all', opacity: 0.8 };

    return h('div', null,
      h(PanelSection, { title: 'Battery' },
        h(PanelSectionRow, null,
          h(ToggleField, {
            label: 'Limit charge to 80%',
            description: status ? (status.module_missing ? 'Needs the acpi_call module (see below)' : hw) : 'Loading...',
            checked: !!(status && status.enabled),
            disabled: busy || installing || !status || !!status.module_missing,
            onChange: onToggle,
          })),
        status && status.error && !status.module_missing
          ? h(PanelSectionRow, null,
              h('div', { style: { color: '#ff7b7b', fontSize: '12px', whiteSpace: 'pre-wrap' } }, status.error))
          : null),

      h(PanelSection, { title: 'System' },
        h(PanelSectionRow, null,
          h(ToggleField, {
            label: 'Unlock system partition',
            description: !status ? 'Loading...'
              : status.readonly === null ? 'State unknown'
              : status.readonly ? 'Locked (read-only, the default)'
              : 'UNLOCKED. Lock it again when you are done.',
            checked: !!(status && status.readonly === false),
            disabled: busy || installing || !status || status.readonly === null,
            onChange: onUnlock,
          }))),

      status && (status.module_missing || installing || (inst && inst.ok === false))
        ? h(PanelSection, { title: 'acpi_call module' },
            h(PanelSectionRow, null,
              h(ButtonItem, {
                layout: 'below',
                disabled: installing,
                onClick: onInstall,
                description: installing ? (inst.step || 'Working...') : 'The charge limit needs this kernel module, which SteamOS does not include.',
              }, installing ? 'Installing...' : 'Install acpi_call')),
            inst && inst.step && !installing
              ? h(PanelSectionRow, null,
                  h('div', { style: { fontSize: '12px', color: inst.ok === false ? '#ff7b7b' : undefined } }, inst.step))
              : null,
            inst && inst.log && inst.log.length
              ? h(PanelSectionRow, null, h('div', { style: mono }, inst.log.join('\n')))
              : null)
        : null);
  }

  const icon = h('svg', { width: '1em', height: '1em', viewBox: '0 0 24 24', fill: 'currentColor' },
    h('path', { d: 'M16 4h-1.5V2h-5v2H8a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h8a2 2 0 0 0 2-2V6a2 2 0 0 0-2-2zm0 16H8V9h8v11z' }));

  return (serverApi) => ({
    title: h('div', { className: staticClasses.Title }, 'Charge Limit'),
    content: h(Content, { serverAPI: serverApi }),
    icon: icon,
    onDismount() {},
  });
})(DFL, SP_REACT);
