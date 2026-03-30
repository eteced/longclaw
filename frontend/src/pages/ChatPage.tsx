import React, { useState, useEffect, useRef, useCallback } from 'react';
import { Send, Loader2, MessageCircle, AlertTriangle, RefreshCw, Wifi, WifiOff } from 'lucide-react';
import { api } from '../services/api';
import type { Message } from '../types';
import { formatDistanceToNow } from 'date-fns';

interface WebChannel {
  id: string | null;
  channel_type: string;
  resident_agent_id: string | null;
  is_active: boolean;
  created_at: string | null;
}

interface InitStatus {
  initialized: boolean;
  has_channel: boolean;
  has_resident_agent: boolean;
}

// WebSocket message types
interface WSMessage {
  type: string;
  data?: {
    content?: string;
    message_id?: string;
    error?: string;
    agent_id?: string;
    status?: string;
    task_id?: string;
    channel_id?: string;
  };
  timestamp?: string;
}

export const ChatPage: React.FC = () => {
  const [messages, setMessages] = useState<Message[]>([]);
  const [inputValue, setInputValue] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [channel, setChannel] = useState<WebChannel | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sendError, setSendError] = useState<string | null>(null);
  const [showInitDialog, setShowInitDialog] = useState(false);
  const [isInitializing, setIsInitializing] = useState(false);
  const [isConnected, setIsConnected] = useState(false);
  const [streamingContent, setStreamingContent] = useState<string>('');
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pingIntervalRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Scroll to bottom of messages
  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  // Connect to WebSocket
  const connectWebSocket = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      return;
    }

    const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsHost = window.location.host;
    // WebSocket endpoint is at /ws, not /api/ws
    const wsUrl = `${wsProtocol}//${wsHost}/ws`;

    console.log('[ChatPage] Connecting to WebSocket:', wsUrl);

    try {
      const ws = new WebSocket(wsUrl);

      ws.onopen = () => {
        console.log('[ChatPage] WebSocket connected');
        setIsConnected(true);

        // Subscribe to channel if available
        const currentChannelId = channel?.id;
        if (currentChannelId) {
          ws.send(JSON.stringify({ action: 'subscribe', channel_id: currentChannelId }));
        }

        // Start ping interval
        if (pingIntervalRef.current) {
          clearInterval(pingIntervalRef.current);
        }
        pingIntervalRef.current = setInterval(() => {
          if (ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ action: 'ping' }));
          }
        }, 25000);
      };

      ws.onmessage = (event) => {
        try {
          const msg: WSMessage = JSON.parse(event.data);
          console.log('[ChatPage] WebSocket message:', msg.type);

          switch (msg.type) {
            case 'stream_chunk':
              if (msg.data?.content) {
                setStreamingContent(prev => prev + msg.data!.content);
              }
              break;

            case 'stream_end':
              if (streamingContent || msg.data?.content) {
                const finalContent = streamingContent + (msg.data?.content || '');
                // Add the completed message
                setMessages(prev => {
                  // Remove any temp streaming message
                  const filtered = prev.filter(m => !m.id.startsWith('streaming-'));
                  return [
                    ...filtered,
                    {
                      id: msg.data?.message_id || `stream-${Date.now()}`,
                      conversation_id: null,
                      sender_type: 'resident' as const,
                      sender_id: channel?.resident_agent_id || '',
                      receiver_type: 'channel' as const,
                      receiver_id: channel?.id || '',
                      message_type: 'text' as const,
                      content: finalContent,
                      metadata: null,
                      task_id: null,
                      subtask_id: null,
                      created_at: new Date().toISOString(),
                    },
                  ];
                });
                setStreamingContent('');
                setIsLoading(false);
              }
              break;

            case 'stream_error':
              setSendError(msg.data?.error || 'Stream error');
              setStreamingContent('');
              setIsLoading(false);
              break;

            case 'message':
              // New message notification
              if (msg.data) {
                loadMessages(channel?.id!);
              }
              break;

            case 'agent_update':
              console.log('[ChatPage] Agent update:', msg.data);
              break;

            case 'pong':
              // Pong received, connection is alive
              break;

            case 'subscribed':
              console.log('[ChatPage] Subscribed to channel:', msg.data?.channel_id);
              break;
          }
        } catch (e) {
          console.error('[ChatPage] Failed to parse WebSocket message:', e);
        }
      };

      ws.onclose = (event) => {
        console.log('[ChatPage] WebSocket closed:', event.code, event.reason);
        setIsConnected(false);

        // Clear ping interval
        if (pingIntervalRef.current) {
          clearInterval(pingIntervalRef.current);
          pingIntervalRef.current = null;
        }

        // Attempt to reconnect after 3 seconds
        if (reconnectTimeoutRef.current) {
          clearTimeout(reconnectTimeoutRef.current);
        }
        reconnectTimeoutRef.current = setTimeout(() => {
          if (channel?.id) {
            console.log('[ChatPage] Attempting to reconnect WebSocket...');
            connectWebSocket();
          }
        }, 3000);
      };

      ws.onerror = (error) => {
        console.error('[ChatPage] WebSocket error:', error);
        setIsConnected(false);
      };

      wsRef.current = ws;
    } catch (error) {
      console.error('[ChatPage] Failed to create WebSocket:', error);
      setIsConnected(false);
    }
  }, [channel?.id, channel?.resident_agent_id, streamingContent]);

  // Disconnect WebSocket
  const disconnectWebSocket = useCallback(() => {
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }
    if (pingIntervalRef.current) {
      clearInterval(pingIntervalRef.current);
      pingIntervalRef.current = null;
    }
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
    setIsConnected(false);
  }, []);

  // Handle 401 unauthorized response
  const handleUnauthorized = () => {
    // Clear API key and dispatch event to trigger re-login
    api.setApiKey(null);
    window.dispatchEvent(new CustomEvent('auth:unauthorized'));
  };

  // Fetch web channel on mount
  useEffect(() => {
    // Clear messages first to avoid showing stale cached data
    setMessages([]);

    const checkAndFetchChannel = async () => {
      try {
        const apiKey = api.getApiKey();
        console.log('[ChatPage] Checking initialization status, API key exists:', !!apiKey);

        // First check initialization status
        const statusResponse = await fetch('/api/chat/init/status', {
          headers: {
            'X-API-Key': apiKey || '',
          },
        });

        console.log('[ChatPage] Init status response:', statusResponse.status);

        // Handle 401 unauthorized
        if (statusResponse.status === 401) {
          console.error('[ChatPage] 401 Unauthorized - API key invalid or expired');
          handleUnauthorized();
          return;
        }

        if (statusResponse.ok) {
          const status: InitStatus = await statusResponse.json();
          console.log('[ChatPage] Init status:', status);

          // If not initialized, show the initialization dialog
          if (!status.initialized) {
            console.log('[ChatPage] Database not initialized, showing init dialog');
            setShowInitDialog(true);
            return;
          }
        }

        // Database is initialized, fetch the channel
        await fetchChannel();
      } catch (err) {
        console.error('[ChatPage] Failed to check init status:', err);
        // Try to fetch channel anyway as fallback
        await fetchChannel();
      }
    };

    const fetchChannel = async () => {
      try {
        const apiKey = api.getApiKey();
        console.log('[ChatPage] Fetching web channel, API key exists:', !!apiKey);

        // Use dedicated web-channel API
        const response = await fetch('/api/chat/web-channel', {
          headers: {
            'X-API-Key': apiKey || '',
          },
        });

        console.log('[ChatPage] Web channel response status:', response.status);

        // Handle 401 unauthorized
        if (response.status === 401) {
          console.error('[ChatPage] 401 Unauthorized - API key invalid or expired');
          handleUnauthorized();
          return;
        }

        if (!response.ok) {
          const errorText = await response.text();
          console.error('[ChatPage] Web channel fetch failed:', response.status, errorText);
          throw new Error(`HTTP ${response.status}: ${errorText}`);
        }

        const webChannel: WebChannel = await response.json();
        console.log('[ChatPage] Web channel data:', webChannel);

        if (webChannel.id && webChannel.is_active) {
          setChannel(webChannel);
          console.log('[ChatPage] Channel set, resident_agent_id:', webChannel.resident_agent_id);
          // Load messages for the channel
          await loadMessages(webChannel.id);
        } else if (webChannel.id && !webChannel.is_active) {
          console.error('[ChatPage] Channel not active');
          setError('Web 聊天频道未激活');
        } else {
          console.error('[ChatPage] No channel found');
          // This shouldn't happen if init status was correct, but handle it
          setShowInitDialog(true);
        }
      } catch (err) {
        console.error('[ChatPage] Failed to fetch web channel:', err);
        setError('无法连接到聊天服务，请刷新页面重试');
      }
    };

    checkAndFetchChannel();
  }, []);

  // Scroll to bottom when messages change
  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  // Connect WebSocket when channel is available
  useEffect(() => {
    if (channel?.id) {
      connectWebSocket();
    }

    return () => {
      disconnectWebSocket();
    };
  }, [channel?.id, connectWebSocket, disconnectWebSocket]);

  // Fallback polling (less frequent, as backup)
  useEffect(() => {
    if (!channel?.id) return;

    // Poll for new messages every 30 seconds as fallback
    const pollInterval = setInterval(() => {
      loadMessages(channel.id!);
    }, 30000);

    return () => clearInterval(pollInterval);
  }, [channel?.id]);

  // Load messages for a channel
  const loadMessages = async (channelId: string) => {
    try {
      const response = await fetch(`/api/chat/messages/${channelId}?limit=100&_t=${Date.now()}`, {
        headers: {
          'X-API-Key': api.getApiKey() || '',
          'Cache-Control': 'no-cache',
        },
      });

      // Handle 401 unauthorized
      if (response.status === 401) {
        console.error('[ChatPage] loadMessages: 401 Unauthorized');
        handleUnauthorized();
        return;
      }

      const data = await response.json();
      const serverMessages: Message[] = data.messages || data.items || [];

      // Merge messages: keep temp messages and update with server messages
      setMessages(prev => {
        // Filter out temp messages that now exist in server response (by content match)
        const tempMessages = prev.filter(m => m.id.startsWith('temp-'));

        // Keep temp messages that don't have a corresponding server message yet
        const keptTempMessages = tempMessages.filter(temp => {
          // Check if there's a server message with same content (meaning temp was saved)
          const matchingServer = serverMessages.find(s =>
            s.content === temp.content && s.sender_type === temp.sender_type
          );
          return !matchingServer;
        });

        // Combine: kept temp messages + server messages (avoiding duplicates)
        const allMessages = [...keptTempMessages, ...serverMessages];

        // Remove duplicates by ID
        const uniqueMessages = allMessages.filter((msg, index, self) =>
          index === self.findIndex(m => m.id === msg.id)
        );

        // Sort by created_at
        uniqueMessages.sort((a, b) =>
          new Date(a.created_at).getTime() - new Date(b.created_at).getTime()
        );

        return uniqueMessages;
      });
    } catch (err) {
      console.error('Failed to load messages:', err);
    }
  };

  // Send a message
  const handleSend = async () => {
    console.log('[ChatPage] handleSend called');
    console.log('[ChatPage] - inputValue:', inputValue);
    console.log('[ChatPage] - isLoading:', isLoading);
    console.log('[ChatPage] - channel:', channel);

    const content = inputValue.trim();

    if (!content) {
      console.log('[ChatPage] Early return: empty content');
      return;
    }
    if (isLoading) {
      console.log('[ChatPage] Early return: already loading');
      return;
    }
    if (!channel?.id) {
      console.log('[ChatPage] Early return: no channel.id');
      setSendError('聊天频道未就绪，请稍后重试');
      return;
    }
    if (!channel?.resident_agent_id) {
      console.log('[ChatPage] Early return: no resident_agent_id');
      setSendError('频道未绑定智能体，请检查配置');
      return;
    }

    console.log('[ChatPage] All checks passed, sending message...');

    // Clear input immediately before sending for better UX
    setInputValue('');
    setIsLoading(true);
    setSendError(null);

    // Add user message immediately for better UX
    const tempUserMsg: Message = {
      id: `temp-${Date.now()}`,
      conversation_id: null,
      sender_type: 'channel',
      sender_id: channel.id,
      receiver_type: 'resident',
      receiver_id: channel.resident_agent_id,
      message_type: 'text',
      content: content,
      metadata: null,
      task_id: null,
      subtask_id: null,
      created_at: new Date().toISOString(),
    };
    setMessages(prev => [...prev, tempUserMsg]);

    try {
      console.log('[ChatPage] Sending POST to /api/chat/send');
      console.log('[ChatPage] Request body:', { channel_id: channel.id, content });

      const apiKey = api.getApiKey();
      console.log('[ChatPage] API key exists:', !!apiKey);

      // Create AbortController for timeout
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 610000); // 10+ min timeout for complex tasks (slightly longer than backend's 600s)

      const response = await fetch('/api/chat/send', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-API-Key': apiKey || '',
        },
        body: JSON.stringify({
          channel_id: channel.id,
          content: content,
        }),
        signal: controller.signal,
      });

      clearTimeout(timeoutId);

      console.log('[ChatPage] Response status:', response.status);

      // Handle 401 unauthorized
      if (response.status === 401) {
        console.error('[ChatPage] 401 Unauthorized - API key invalid or expired');
        handleUnauthorized();
        throw new Error('登录已过期，请重新登录');
      }

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        const errorMsg = errorData.detail || `请求失败 (${response.status})`;
        console.error('[ChatPage] Send failed:', errorMsg);
        throw new Error(errorMsg);
      }

      const data = await response.json();
      console.log('[ChatPage] Send success, message_id:', data.message_id);

      // Remove temp message and add real messages
      setMessages(prev => {
        const filtered = prev.filter(m => !m.id.startsWith('temp-'));
        return [
          ...filtered,
          {
            id: data.message_id,
            conversation_id: null,
            sender_type: 'channel' as const,
            sender_id: channel.id!,
            receiver_type: 'resident' as const,
            receiver_id: channel.resident_agent_id,
            message_type: 'text' as const,
            content: content,
            metadata: null,
            task_id: null,
            subtask_id: null,
            created_at: data.created_at,
          },
          {
            id: `reply-${data.message_id}`,
            conversation_id: null,
            sender_type: 'resident' as const,
            sender_id: channel.resident_agent_id,
            receiver_type: 'channel' as const,
            receiver_id: channel.id!,
            message_type: 'text' as const,
            content: data.reply,
            metadata: null,
            task_id: null,
            subtask_id: null,
            created_at: data.created_at,
          },
        ];
      });
    } catch (err) {
      console.error('[ChatPage] Failed to send message:', err);
      const errorMessage = err instanceof Error
        ? (err.name === 'AbortError' ? '请求超时，请重试' : err.message)
        : '发送失败，请重试';
      setSendError(errorMessage);
      // Remove temp message on error and restore input
      setMessages(prev => prev.filter(m => !m.id.startsWith('temp-')));
      setInputValue(content); // Restore input on error so user doesn't lose their message
    } finally {
      console.log('[ChatPage] Setting isLoading to false');
      setIsLoading(false);
    }
  };

  // Handle Enter key
  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  // Handle initialization
  const handleInitialize = async () => {
    console.log('[ChatPage] Starting database initialization...');
    setIsInitializing(true);

    try {
      const apiKey = api.getApiKey();
      const response = await fetch('/api/chat/init', {
        method: 'POST',
        headers: {
          'X-API-Key': apiKey || '',
        },
      });

      const data = await response.json();
      console.log('[ChatPage] Init response:', data);

      if (data.success) {
        console.log('[ChatPage] Initialization successful, refreshing page...');
        // Refresh the page to load with initialized data
        window.location.reload();
      } else {
        console.error('[ChatPage] Initialization failed:', data.message);
        setError(`初始化失败: ${data.message}`);
        setIsInitializing(false);
      }
    } catch (err) {
      console.error('[ChatPage] Initialization error:', err);
      setError('初始化失败，请重试');
      setIsInitializing(false);
    }
  };

  // Handle cancel initialization
  const handleCancelInit = () => {
    setShowInitDialog(false);
    setError('系统未初始化，Chat 功能不可用');
  };

  // Format time - show relative time for recent messages, absolute time for older ones
  const formatTime = (dateStr: string) => {
    // If the date string doesn't end with 'Z', append it to treat as UTC
    const utcStr = dateStr.endsWith('Z') ? dateStr : dateStr + 'Z';
    const date = new Date(utcStr);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffMins = Math.floor(diffMs / 60000);

    // Show relative time for messages less than 1 hour old
    if (diffMins < 60) {
      return formatDistanceToNow(date, { addSuffix: true });
    }

    // Show absolute time for older messages
    return date.toLocaleTimeString('zh-CN', {
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  // Check if message is from user
  const isUserMessage = (msg: Message) => {
    return msg.sender_type === 'channel';
  };

  return (
    <div className="flex flex-col h-[calc(100vh-180px)]">
      {/* Header */}
      <div className="bg-white border-b border-gray-200 px-4 py-3 mb-4 rounded-lg">
        <div className="flex items-center justify-between">
          <div className="flex items-center">
            <MessageCircle className="w-5 h-5 text-blue-600 mr-2" />
            <h2 className="text-lg font-semibold text-gray-900">和老六聊天</h2>
          </div>
          <div className="flex items-center space-x-2">
            {isConnected ? (
              <>
                <Wifi className="w-4 h-4 text-green-500" />
                <span className="text-sm text-green-600 bg-green-50 px-2 py-1 rounded">
                  已连接
                </span>
              </>
            ) : (
              <>
                <WifiOff className="w-4 h-4 text-yellow-500" />
                <span className="text-sm text-yellow-600 bg-yellow-50 px-2 py-1 rounded">
                  {channel?.id ? '重连中...' : '连接中...'}
                </span>
              </>
            )}
          </div>
        </div>
      </div>

      {/* Initialization Dialog */}
      {showInitDialog && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg shadow-xl max-w-md w-full mx-4 p-6">
            <div className="flex items-center mb-4">
              <AlertTriangle className="w-8 h-8 text-orange-500 mr-3" />
              <h3 className="text-lg font-semibold text-gray-900">系统初始化</h3>
            </div>
            <div className="mb-6">
              <p className="text-gray-600 mb-3">
                系统检测到数据库未初始化。
              </p>
              <p className="text-gray-600 mb-3">
                初始化将清除所有现有数据并创建默认配置：
              </p>
              <ul className="text-sm text-gray-500 list-disc list-inside mb-3">
                <li>创建默认 Web 聊天频道</li>
                <li>创建智能体"老六"并绑定到频道</li>
              </ul>
              <p className="text-red-500 text-sm">
                警告：所有现有数据将被永久删除！
              </p>
            </div>
            <div className="flex space-x-3">
              <button
                onClick={handleCancelInit}
                disabled={isInitializing}
                className="flex-1 px-4 py-2 border border-gray-300 rounded-lg text-gray-700 hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              >
                取消
              </button>
              <button
                onClick={handleInitialize}
                disabled={isInitializing}
                className="flex-1 px-4 py-2 bg-blue-500 text-white rounded-lg hover:bg-blue-600 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center justify-center"
              >
                {isInitializing ? (
                  <>
                    <RefreshCw className="w-4 h-4 mr-2 animate-spin" />
                    初始化中...
                  </>
                ) : (
                  '初始化'
                )}
              </button>
            </div>
            <p className="text-xs text-gray-400 mt-3 text-center">
              取消后 Chat 功能将不可用
            </p>
          </div>
        </div>
      )}

      {/* Messages */}
      <div className="flex-1 overflow-y-auto bg-white rounded-lg border border-gray-200 p-4 mb-4">
        {messages.length === 0 && !streamingContent ? (
          <div className="flex flex-col items-center justify-center h-full text-gray-400">
            <MessageCircle className="w-12 h-12 mb-2" />
            <p>开始和老六聊天吧！</p>
          </div>
        ) : (
          <div className="space-y-4">
            {messages.map((msg) => (
              <div
                key={msg.id}
                className={`flex ${isUserMessage(msg) ? 'justify-end' : 'justify-start'}`}
              >
                <div
                  className={`max-w-[70%] rounded-lg px-4 py-2 ${
                    isUserMessage(msg)
                      ? 'bg-blue-500 text-white'
                      : 'bg-gray-100 text-gray-900'
                  }`}
                >
                  <p className="whitespace-pre-wrap">{msg.content}</p>
                  <p
                    className={`text-xs mt-1 ${
                      isUserMessage(msg) ? 'text-blue-100' : 'text-gray-400'
                    }`}
                  >
                    {formatTime(msg.created_at)}
                  </p>
                </div>
              </div>
            ))}
            {/* Streaming message */}
            {streamingContent && (
              <div className="flex justify-start">
                <div className="max-w-[70%] rounded-lg px-4 py-2 bg-gray-100 text-gray-900">
                  <p className="whitespace-pre-wrap">{streamingContent}</p>
                  <p className="text-xs mt-1 text-gray-400 flex items-center">
                    <Loader2 className="w-3 h-3 mr-1 animate-spin" />
                    正在输入...
                  </p>
                </div>
              </div>
            )}
            {/* Loading indicator when waiting for response */}
            {isLoading && !streamingContent && (
              <div className="flex justify-start">
                <div className="max-w-[70%] rounded-lg px-4 py-2 bg-gray-100 text-gray-900">
                  <p className="text-gray-500 flex items-center">
                    <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                    AI 正在思考...
                  </p>
                </div>
              </div>
            )}
            <div ref={messagesEndRef} />
          </div>
        )}
      </div>

      {/* Connection error message */}
      {error && (
        <div className="bg-red-50 text-red-600 px-4 py-2 rounded-lg mb-4 text-sm">
          {error}
        </div>
      )}

      {/* Send error message */}
      {sendError && (
        <div className="bg-orange-50 text-orange-600 px-4 py-2 rounded-lg mb-4 text-sm flex items-center justify-between">
          <span>{sendError}</span>
          <button
            onClick={() => setSendError(null)}
            className="text-orange-400 hover:text-orange-600 ml-2"
          >
            ✕
          </button>
        </div>
      )}

      {/* Input */}
      <div className="bg-white rounded-lg border border-gray-200 p-4">
        <div className="flex space-x-2">
          <input
            type="text"
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            onKeyPress={handleKeyPress}
            placeholder="输入消息..."
            disabled={isLoading || !channel?.id}
            className="flex-1 border border-gray-300 rounded-lg px-4 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent disabled:bg-gray-100 disabled:cursor-not-allowed"
          />
          <button
            onClick={handleSend}
            disabled={isLoading || !inputValue.trim() || !channel?.id}
            className="bg-blue-500 text-white rounded-lg px-4 py-2 hover:bg-blue-600 focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors"
          >
            {isLoading ? (
              <Loader2 className="w-5 h-5 animate-spin" />
            ) : (
              <Send className="w-5 h-5" />
            )}
          </button>
        </div>
      </div>
    </div>
  );
};

export default ChatPage;
