import React, { useMemo } from 'react';
import { useStore } from 'App/mstore';
import KeyboardHelp from 'Components/Session_/Player/Controls/components/KeyboardHelp';
import { Icon, Tooltip } from 'UI';
import QueueControls from './QueueControls';
import Bookmark from 'Shared/Bookmark';
import SharePopup from '../shared/SharePopup/SharePopup';
import Issues from './Issues/Issues';
import NotePopup from './components/NotePopup';
import { useModal } from 'App/components/Modal';
import BugReportModal from './BugReport/BugReportModal';
import { PlayerContext } from 'App/components/Session/playerContext';
import { observer } from 'mobx-react-lite';
import { connect } from 'react-redux';
import SessionTabs from 'Components/Session/Player/SharedComponents/SessionTabs';
import { IFRAME } from 'App/constants/storageKeys';
import cn from 'classnames';
import { Switch, Button as AntButton, Popover } from 'antd';
import { BugOutlined, ShareAltOutlined } from '@ant-design/icons';

const localhostWarn = (project) => project + '_localhost_warn';
const disableDevtools = 'or_devtools_uxt_toggle';

function SubHeader(props) {
  const localhostWarnKey = localhostWarn(props.siteId);
  const defaultLocalhostWarn = localStorage.getItem(localhostWarnKey) !== '1';
  const [showWarningModal, setWarning] = React.useState(defaultLocalhostWarn);
  const { player, store } = React.useContext(PlayerContext);
  const { width, height, endTime, location: currentLocation = 'loading...' } = store.get();
  const hasIframe = localStorage.getItem(IFRAME) === 'true';
  const { uxtestingStore } = useStore();

  const enabledIntegration = useMemo(() => {
    const { integrations } = props;
    if (!integrations || !integrations.size) {
      return false;
    }

    return integrations.some((i) => i.token);
  }, [props.integrations]);

  const { showModal, hideModal } = useModal();

  const location =
    currentLocation && currentLocation.length > 70
      ? `${currentLocation.slice(0, 25)}...${currentLocation.slice(-40)}`
      : currentLocation;

  const showReportModal = () => {
    const { tabStates, currentTab } = store.get();
    const resourceList = tabStates[currentTab]?.resourceList || [];
    const exceptionsList = tabStates[currentTab]?.exceptionsList || [];
    const eventsList = tabStates[currentTab]?.eventList || [];
    const graphqlList = tabStates[currentTab]?.graphqlList || [];
    const fetchList = tabStates[currentTab]?.fetchList || [];

    const mappedResourceList = resourceList
      .filter((r) => r.isRed || r.isYellow)
      .concat(fetchList.filter((i) => parseInt(i.status) >= 400))
      .concat(graphqlList.filter((i) => parseInt(i.status) >= 400));

    player.pause();
    const xrayProps = {
      currentLocation: currentLocation,
      resourceList: mappedResourceList,
      exceptionsList: exceptionsList,
      eventsList: eventsList,
      endTime: endTime,
    };
    showModal(
      <BugReportModal width={width} height={height} xrayProps={xrayProps} hideModal={hideModal} />,
      { right: true, width: 620 }
    );
  };

  const showWarning =
    location && /(localhost)|(127.0.0.1)|(0.0.0.0)/.test(location) && showWarningModal;
  const closeWarning = () => {
    localStorage.setItem(localhostWarnKey, '1');
    setWarning(false);
  };

  const toggleDevtools = (enabled) => {
    localStorage.setItem(disableDevtools, enabled ? '0' : '1');
    uxtestingStore.setHideDevtools(!enabled);
  };

  return (
    <>
      <div
        className="w-full px-4 flex items-center border-b relative"
        style={{
          background: uxtestingStore.isUxt() ? (props.live ? '#F6FFED' : '#EBF4F5') : undefined,
        }}
      >
        {showWarning ? (
          <div
            className="px-3 py-1 border border-gray-lighter drop-shadow-md rounded bg-active-blue flex items-center justify-between"
            style={{
              zIndex: 999,
              position: 'absolute',
              left: '50%',
              bottom: '-24px',
              transform: 'translate(-50%, 0)',
              fontWeight: 500,
            }}
          >
            Some assets may load incorrectly on localhost.
            <a
              href="https://docs.openreplay.com/en/troubleshooting/session-recordings/#testing-in-localhost"
              target="_blank"
              rel="noreferrer"
              className="link ml-1"
            >
              Learn More
            </a>
            <div className="py-1 ml-3 cursor-pointer" onClick={closeWarning}>
              <Icon name="close" size={16} color="black" />
            </div>
          </div>
        ) : null}
        <SessionTabs />
        <div
          className={cn(
            'ml-auto text-sm flex items-center color-gray-medium gap-2',
            hasIframe ? 'opacity-50 pointer-events-none' : ''
          )}
          style={{ width: 'max-content' }}
        >
          <KeyboardHelp />
          <Popover content={'Create Bug Report'}>
            <AntButton
              size={'small'}
              className={'flex items-center justify-center'}
              onClick={showReportModal}
            >
              <BugOutlined />
            </AntButton>
          </Popover>
          <Bookmark sessionId={props.sessionId} />
          <NotePopup />
          {enabledIntegration && <Issues sessionId={props.sessionId} />}
          <SharePopup
            entity="sessions"
            id={props.sessionId}
            showCopyLink={true}
            trigger={
              <div className="relative">
                <Popover content={'Share Session'}>
                  <AntButton size={'small'} className="flex items-center justify-center">
                    <ShareAltOutlined />
                  </AntButton>
                </Popover>
              </div>
            }
          />

          {uxtestingStore.isUxt() ? (
            <Switch
              checkedChildren={'DevTools'}
              unCheckedChildren={'DevTools'}
              onChange={toggleDevtools}
              defaultChecked={!uxtestingStore.hideDevtools}
            />
          ) : (
            <div>
              <QueueControls />
            </div>
          )}
        </div>
      </div>
      {location && (
        <div className={'w-full bg-white border-b border-gray-lighter'}>
          <div className="flex w-fit items-center cursor-pointer color-gray-medium text-sm p-1">
            <Icon size="20" name="event/link" className="mr-1" />
            <Tooltip title="Open in new tab" delay={0}>
              <a href={currentLocation} target="_blank">
                {location}
              </a>
            </Tooltip>
          </div>
        </div>
      )}
    </>
  );
}

export default connect((state) => ({
  siteId: state.getIn(['site', 'siteId']),
  integrations: state.getIn(['issues', 'list']),
  modules: state.getIn(['user', 'account', 'modules']) || [],
}))(observer(SubHeader));
