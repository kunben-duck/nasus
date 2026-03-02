package com.autotest.platform.dto;

import com.fasterxml.jackson.annotation.JsonInclude;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.List;
import java.util.Map;

@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@JsonInclude(JsonInclude.Include.NON_NULL)
public class DashboardDTO {
    
    private Statistics statistics;
    private Charts charts;
    private RecentActivities recentActivities;
    private SystemStatus systemStatus;
    
    @Data
    @Builder
    @NoArgsConstructor
    @AllArgsConstructor
    public static class Statistics {
        private Long totalProjects;
        private Long totalUserStories;
        private Long totalTestCases;
        private Long totalScripts;
        private Long totalExecutions;
        private Long pendingExecutions;
        private Long runningExecutions;
        private Double successRate;
        private Double averageExecutionTime;
    }
    
    @Data
    @Builder
    @NoArgsConstructor
    @AllArgsConstructor
    public static class Charts {
        private List<ChartData> executionTrend;
        private List<ChartData> testCaseDistribution;
        private List<ChartData> executionResults;
        private List<ChartData> scriptStatus;
    }
    
    @Data
    @Builder
    @NoArgsConstructor
    @AllArgsConstructor
    public static class ChartData {
        private String label;
        private Long value;
        private String color;
    }
    
    @Data
    @Builder
    @NoArgsConstructor
    @AllArgsConstructor
    public static class RecentActivities {
        private List<ActivityItem> recentExecutions;
        private List<ActivityItem> recentUserStories;
        private List<ActivityItem> recentScripts;
    }
    
    @Data
    @Builder
    @NoArgsConstructor
    @AllArgsConstructor
    public static class ActivityItem {
        private String id;
        private String type;
        private String title;
        private String status;
        private String timestamp;
        private String user;
    }
    
    @Data
    @Builder
    @NoArgsConstructor
    @AllArgsConstructor
    public static class SystemStatus {
        private String databaseStatus;
        private String redisStatus;
        private String rabbitmqStatus;
        private String aiServiceStatus;
        private Long activeExecutors;
        private Long queuedTasks;
    }
}
