(function () {
  'use strict';

  function serverOffset(serverNow) {
    var parsed = Date.parse(serverNow || '');
    return Number.isFinite(parsed) ? parsed - Date.now() : 0;
  }

  function monitorTaskButton(button) {
    var start = Date.parse(button.dataset.taskStartAt || '');
    var end = Date.parse(button.dataset.taskEndAt || '');
    var offset = serverOffset(button.dataset.taskServerNow);
    var label = button.querySelector('[data-task-window-label]');
    if (!Number.isFinite(start) || !Number.isFinite(end) || !label) return;

    button.addEventListener('click', function () {
      if (!button.disabled && button.dataset.taskUrl) {
        var taskUrl = new URL(button.dataset.taskUrl, window.location.href);
        var context = window.ATRUE_CTX
          || new URL(window.location.href).searchParams.get('ctx');
        if (context) taskUrl.searchParams.set('ctx', context);
        window.location.assign(taskUrl.pathname + taskUrl.search + taskUrl.hash);
      }
    });

    function refresh() {
      var now = Date.now() + offset;
      if (now < start) {
        button.disabled = true;
        label.textContent = 'Upcoming';
      } else if (now >= end) {
        button.disabled = true;
        label.textContent = 'Time Ended';
        return;
      } else {
        button.disabled = false;
        label.textContent = button.dataset.taskReadyLabel || 'Do the Task';
      }

      var boundary = now < start ? start : end;
      window.setTimeout(refresh, Math.max(0, Math.min(boundary - now, 2147483000)));
    }

    refresh();
    document.addEventListener('visibilitychange', function () {
      if (!document.hidden) refresh();
    });
  }

  function monitorActiveTask() {
    var node = document.getElementById('activeSimulationTaskSchedule');
    if (!node) return;
    var schedule;
    try {
      schedule = JSON.parse(node.textContent);
    } catch (_error) {
      return;
    }
    if (!schedule || !schedule.end_at || !schedule.start_at) return;

    var start = Date.parse(schedule.start_at);
    var end = Date.parse(schedule.end_at);
    var offset = serverOffset(schedule.server_now);
    if (!Number.isFinite(start) || !Number.isFinite(end)) return;

    function refresh() {
      var now = Date.now() + offset;
      var state = now < start ? 'upcoming' : now >= end ? 'expired' : 'available';
      var status = document.querySelector('[data-task-schedule-status]');
      if (status && status.dataset.taskCompleted !== 'true') {
        status.textContent = state === 'upcoming' ? 'Upcoming'
          : state === 'expired' ? 'Expired'
            : status.dataset.taskStarted === 'true' ? 'In Progress' : 'Not Started';
      }

      document.querySelectorAll('.sim-task[data-task-base-state]').forEach(function (task) {
        var taskStatus = task.querySelector('.sim-task-status');
        var baseState = task.dataset.taskBaseState;
        if (!taskStatus || ['completed', 'failed', 'cancelled'].includes(baseState)) return;
        var displayState = state === 'upcoming' ? 'upcoming'
          : state === 'expired' ? 'expired' : baseState;
        task.classList.remove('sim-task--upcoming', 'sim-task--expired');
        task.classList.add('sim-task--' + displayState);
        taskStatus.textContent = displayState === 'upcoming' ? 'Upcoming'
          : displayState === 'expired' ? 'Expired'
            : displayState === 'untracked' ? 'Not tracked'
              : displayState === 'pending_verification' ? 'Pending verification' : 'Pending';
      });

      if (state === 'expired') {
        if (schedule.redirect_on_end) {
          window.location.replace(schedule.role_detail_url);
        }
        return;
      }

      var boundary = now < start ? start : end;
      window.setTimeout(refresh, Math.max(0, Math.min(boundary - now, 1000)));
    }

    refresh();
    document.addEventListener('visibilitychange', function () {
      if (!document.hidden) refresh();
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('[data-task-window-button]').forEach(monitorTaskButton);
    monitorActiveTask();
  });
}());
