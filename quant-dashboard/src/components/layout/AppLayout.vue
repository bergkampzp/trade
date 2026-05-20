<script setup lang="ts">
</script>

<template>
  <div class="app-layout">
    <header class="app-header">
      <div class="flex items-center gap-3">
        <span class="text-lg font-bold text-amber-400">Quant Research</span>
      </div>
      <slot name="header" />
    </header>
    <aside class="app-sidebar">
      <slot name="sidebar" />
    </aside>
    <main class="app-main">
      <slot name="main" />
    </main>
  </div>
</template>

<style scoped>
.app-layout {
  display: grid;
  grid-template-areas:
    "header header"
    "sidebar main";
  grid-template-columns: 280px 1fr;
  grid-template-rows: 48px 1fr;
  height: 100vh;
  background: #0f0f1a;
  color: #d1d5db;
}
.app-header {
  grid-area: header;
  display: flex;
  align-items: center;
  padding: 0 16px;
  background: #1a1a2e;
  border-bottom: 1px solid #2a2a3e;
}
.app-sidebar {
  grid-area: sidebar;
  overflow-y: auto;
  border-right: 1px solid #2a2a3e;
  background: #12121f;
}
.app-main {
  grid-area: main;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
</style>
