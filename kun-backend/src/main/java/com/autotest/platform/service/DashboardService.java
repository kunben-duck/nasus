package com.autotest.platform.service;

import com.autotest.platform.dto.DashboardDTO;
import com.autotest.platform.entity.TestCase;
import com.autotest.platform.entity.TestExecution;
import com.autotest.platform.entity.TestScript;
import com.autotest.platform.entity.Tenant;
import com.autotest.platform.repository.TestCaseRepository;
import com.autotest.platform.repository.TestExecutionRepository;
import com.autotest.platform.repository.TestScriptRepository;
import com.autotest.platform.repository.UserStoryRepository;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.data.domain.PageRequest;
import org.springframework.data.domain.Sort;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDate;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

@Service
@RequiredArgsConstructor
@Slf4j
public class DashboardService {

    private static final List<Integer> ALLOWED_TREND_DAYS = List.of(7, 30, 90);

    private final UserStoryRepository userStoryRepository;
    private final TestCaseRepository testCaseRepository;
    private final TestScriptRepository testScriptRepository;
    private final TestExecutionRepository testExecutionRepository;
    private final TenantContextService tenantContextService;

    @Transactional(readOnly = true)
    public DashboardDTO getDashboardData() {
        return getDashboardData(7);
    }

    @Transactional(readOnly = true)
    public DashboardDTO getDashboardData(Integer trendDays) {
        int normalizedTrendDays = normalizeTrendDays(trendDays);
        TenantContextService.CurrentTenant currentTenant = tenantContextService.resolveCurrentTenant();
        Long tenantId = currentTenant.tenant().getId();

        return DashboardDTO.builder()
                .statistics(getStatistics(currentTenant))
                .charts(getCharts(tenantId, normalizedTrendDays))
                .recentActivities(getRecentActivities(tenantId))
                .systemStatus(getSystemStatus(tenantId))
                .build();
    }

    private DashboardDTO.Statistics getStatistics(TenantContextService.CurrentTenant currentTenant) {
        Long tenantId = currentTenant.tenant().getId();
        long totalProjects = currentTenant.memberships().stream()
                .filter(item -> item.getTenant() != null && item.getTenant().getStatus() == Tenant.TenantStatus.ACTIVE)
                .count();
        long totalUS = userStoryRepository.countByTenantId(tenantId);
        long totalTC = testCaseRepository.countByTenantId(tenantId);
        long totalScripts = testScriptRepository.countByTenantId(tenantId);
        long totalExecutions = testExecutionRepository.countByTenantId(tenantId);
        long pendingExecs = testExecutionRepository.countByStatus(tenantId, TestExecution.ExecutionStatus.PENDING);
        long runningExecs = testExecutionRepository.countByStatus(tenantId, TestExecution.ExecutionStatus.RUNNING);

        long passedExecutions = testExecutionRepository.countByResult(tenantId, TestExecution.ExecutionResult.PASS);
        double successRate = totalExecutions > 0 ? (double) passedExecutions / totalExecutions * 100 : 0;

        Double avgDuration = testExecutionRepository.getAverageDuration(tenantId);

        return DashboardDTO.Statistics.builder()
                .totalProjects(totalProjects)
                .totalUserStories(totalUS)
                .totalTestCases(totalTC)
                .totalScripts(totalScripts)
                .totalExecutions(totalExecutions)
                .pendingExecutions(pendingExecs)
                .runningExecutions(runningExecs)
                .successRate(Math.round(successRate * 100.0) / 100.0)
                .averageExecutionTime(avgDuration != null ? Math.round(avgDuration / 1000.0 * 100.0) / 100.0 : 0)
                .build();
    }

    private DashboardDTO.Charts getCharts(Long tenantId, int trendDays) {
        int windowDays = Math.max(1, trendDays);
        List<DashboardDTO.ChartData> executionTrend = new ArrayList<>();
        LocalDate today = LocalDate.now();
        LocalDateTime from = today.minusDays(windowDays - 1L).atStartOfDay();
        LocalDateTime to = today.plusDays(1).atStartOfDay();
        List<TestExecution> recent = testExecutionRepository.findByTimeRange(tenantId, from, to);
        Map<LocalDate, Long> dayCounter = new HashMap<>();
        for (TestExecution execution : recent) {
            if (execution.getCreatedAt() == null) {
                continue;
            }
            LocalDate day = execution.getCreatedAt().toLocalDate();
            dayCounter.put(day, dayCounter.getOrDefault(day, 0L) + 1L);
        }
        for (int i = windowDays - 1; i >= 0; i--) {
            LocalDate day = today.minusDays(i);
            Long value = dayCounter.getOrDefault(day, 0L);
            executionTrend.add(DashboardDTO.ChartData.builder()
                    .label(day.getMonthValue() + "-" + String.format("%02d", day.getDayOfMonth()))
                    .value(value)
                    .color("#00d4ff")
                    .build());
        }

        List<DashboardDTO.ChartData> testCaseDistribution = List.of(
                DashboardDTO.ChartData.builder()
                        .label("UI")
                        .value(testCaseRepository.countByTestType(tenantId, TestCase.TestType.UI))
                        .color("#00d4ff")
                        .build(),
                DashboardDTO.ChartData.builder()
                        .label("API")
                        .value(testCaseRepository.countByTestType(tenantId, TestCase.TestType.API))
                        .color("#7c3aed")
                        .build(),
                DashboardDTO.ChartData.builder()
                        .label("Functional")
                        .value(testCaseRepository.countByTestType(tenantId, TestCase.TestType.FUNCTIONAL))
                        .color("#10b981")
                        .build(),
                DashboardDTO.ChartData.builder()
                        .label("Performance")
                        .value(testCaseRepository.countByTestType(tenantId, TestCase.TestType.PERFORMANCE))
                        .color("#f59e0b")
                        .build()
        );

        List<DashboardDTO.ChartData> executionResults = List.of(
                DashboardDTO.ChartData.builder()
                        .label("Pass")
                        .value(testExecutionRepository.countByResult(tenantId, TestExecution.ExecutionResult.PASS))
                        .color("#10b981")
                        .build(),
                DashboardDTO.ChartData.builder()
                        .label("Fail")
                        .value(testExecutionRepository.countByResult(tenantId, TestExecution.ExecutionResult.FAIL))
                        .color("#ef4444")
                        .build(),
                DashboardDTO.ChartData.builder()
                        .label("Error")
                        .value(testExecutionRepository.countByResult(tenantId, TestExecution.ExecutionResult.ERROR))
                        .color("#f59e0b")
                        .build(),
                DashboardDTO.ChartData.builder()
                        .label("Skip")
                        .value(testExecutionRepository.countByResult(tenantId, TestExecution.ExecutionResult.SKIP))
                        .color("#6b7280")
                        .build()
        );

        List<DashboardDTO.ChartData> scriptStatus = List.of(
                DashboardDTO.ChartData.builder()
                        .label("Ready")
                        .value(testScriptRepository.countByStatus(tenantId, TestScript.Status.READY))
                        .color("#10b981")
                        .build(),
                DashboardDTO.ChartData.builder()
                        .label("Draft")
                        .value(testScriptRepository.countByStatus(tenantId, TestScript.Status.DRAFT))
                        .color("#6b7280")
                        .build(),
                DashboardDTO.ChartData.builder()
                        .label("Generating")
                        .value(testScriptRepository.countByStatus(tenantId, TestScript.Status.GENERATING))
                        .color("#00d4ff")
                        .build()
        );

        return DashboardDTO.Charts.builder()
                .executionTrend(executionTrend)
                .testCaseDistribution(testCaseDistribution)
                .executionResults(executionResults)
                .scriptStatus(scriptStatus)
                .build();
    }

    private DashboardDTO.RecentActivities getRecentActivities(Long tenantId) {
        List<DashboardDTO.ActivityItem> recentExecutions = testExecutionRepository
                .findRecentExecutions(tenantId, PageRequest.of(0, 5))
                .stream()
                .map(exec -> DashboardDTO.ActivityItem.builder()
                        .id(exec.getExecutionId())
                        .type("execution")
                        .title(exec.getTestCase() != null ? exec.getTestCase().getTitle() : "Unknown")
                        .status(exec.getStatus().name())
                        .timestamp(exec.getCreatedAt().toString())
                        .user(exec.getExecutedBy())
                        .build())
                .collect(Collectors.toList());

        List<DashboardDTO.ActivityItem> recentUS = userStoryRepository
                .findByTenantId(tenantId, PageRequest.of(0, 5, Sort.by(Sort.Direction.DESC, "createdAt")))
                .getContent()
                .stream()
                .map(us -> DashboardDTO.ActivityItem.builder()
                        .id(us.getUsNumber())
                        .type("userStory")
                        .title(us.getTitle())
                        .status(us.getStatus().name())
                        .timestamp(us.getCreatedAt().toString())
                        .user(us.getCreatedBy() != null ? us.getCreatedBy().getUsername() : "System")
                        .build())
                .collect(Collectors.toList());

        List<DashboardDTO.ActivityItem> recentScripts = testScriptRepository
                .findByTenantId(tenantId, PageRequest.of(0, 5, Sort.by(Sort.Direction.DESC, "createdAt")))
                .getContent()
                .stream()
                .map(script -> DashboardDTO.ActivityItem.builder()
                        .id(script.getId().toString())
                        .type("script")
                        .title(script.getName())
                        .status(script.getStatus().name())
                        .timestamp(script.getCreatedAt().toString())
                        .user("System")
                        .build())
                .collect(Collectors.toList());

        return DashboardDTO.RecentActivities.builder()
                .recentExecutions(recentExecutions)
                .recentUserStories(recentUS)
                .recentScripts(recentScripts)
                .build();
    }

    private DashboardDTO.SystemStatus getSystemStatus(Long tenantId) {
        return DashboardDTO.SystemStatus.builder()
                .databaseStatus("Connected")
                .redisStatus("Connected")
                .rabbitmqStatus("Redis Queue")
                .aiServiceStatus("Available")
                .activeExecutors(testExecutionRepository.countByStatus(tenantId, TestExecution.ExecutionStatus.RUNNING))
                .queuedTasks(testExecutionRepository.countByStatus(tenantId, TestExecution.ExecutionStatus.PENDING))
                .build();
    }

    private int normalizeTrendDays(Integer trendDays) {
        if (trendDays == null) {
            return 7;
        }
        return ALLOWED_TREND_DAYS.contains(trendDays) ? trendDays : 7;
    }
}
