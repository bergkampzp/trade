<template>
  <div class="hermes-chat">
    <SessionSidebar />
    <div class="chat-main">
      <EmptyState v-if="store.status === 'empty' && !store.messages.length" />
      <ChatArea v-else />
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted } from 'vue'
import { useHermesStore } from '../../stores/hermes'
import SessionSidebar from './SessionSidebar.vue'
import ChatArea from './ChatArea.vue'
import EmptyState from './EmptyState.vue'

const store = useHermesStore()

onMounted(() => {
  store.loadSkills()
  store.loadSessions()
})
</script>

<style scoped>
.hermes-chat {
  display: flex;
  height: 100%;
  min-height: 0;
  background: #0f1729;
  color: #e2e8f0;
}

.chat-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
  overflow: hidden;
}
</style>
