"""Bounded Redis retention shared by queue completion and conversation writes."""
TTL_SECONDS = 3600
MAX_STATE_RECORDS = 1024
MAX_RECORD_BYTES = 16384
STATE_INDEX = "state:expirations"

STATE_LUA = """
local function save_state(index, key, item, now)
    local expired = redis.call('ZRANGEBYSCORE', index, '-inf', now)
    for _, old in ipairs(expired) do redis.call('DEL', old); redis.call('ZREM', index, old) end
    if item == cjson.null then
        redis.call('DEL', key); redis.call('ZREM', index, key); return
    end
    local ttl = math.min(3600, math.max(1, item.ttl))
    redis.call('SET', key, item.value, 'EX', ttl)
    redis.call('ZADD', index, now + ttl, key)
    local overflow = redis.call('ZCARD', index) - 1024
    if overflow > 0 then
        local oldest = redis.call('ZRANGE', index, 0, overflow - 1)
        for _, old in ipairs(oldest) do redis.call('DEL', old); redis.call('ZREM', index, old) end
    end
    redis.call('EXPIRE', index, 3600)
end
"""
