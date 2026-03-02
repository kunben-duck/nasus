package com.autotest.platform.dto;

import com.fasterxml.jackson.annotation.JsonInclude;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.LocalDateTime;
import java.util.List;

@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@JsonInclude(JsonInclude.Include.NON_NULL)
public class TestExecutionDTO {
    
    private Long id;
    private String executionId;
    private TestCaseDTO testCase;
    private Long scriptId;
    private String scriptName;
    private String scriptStatus;
    private String scriptRecordId;
    private Boolean previewMode;
    private ExecutionStatus status;
    private ExecutionResult result;
    private String logs;
    private String errorMessage;
    private String videoPath;
    private String reportPath;
    private Long duration;
    private String executedBy;
    private String browser;
    private String environment;
    private List<ExecutionScreenshotDTO> screenshots;
    private List<ExecutionTimelineDTO> timeline;
    private LocalDateTime createdAt;
    private LocalDateTime startedAt;
    private LocalDateTime completedAt;
    
    public enum ExecutionStatus {
        PENDING, QUEUED, RUNNING, PAUSED, COMPLETED, CANCELLED, FAILED, TIMEOUT
    }
    
    public enum ExecutionResult {
        PASS, FAIL, SKIP, ERROR, WARNING
    }
    
    @Data
    @Builder
    @NoArgsConstructor
    @AllArgsConstructor
    public static class CreateRequest {
        private Long testCaseId;
        private Long scriptId;
        private String scriptRecordId;
        private Boolean previewMode;
        private String browser;
        private String environment;
    }
    
    @Data
    @Builder
    @NoArgsConstructor
    @AllArgsConstructor
    public static class ExecutionScreenshotDTO {
        private String filePath;
        private String stepName;
        private Integer stepNumber;
        private String description;
        private String type;
        private LocalDateTime capturedAt;
    }
    
    @Data
    @Builder
    @NoArgsConstructor
    @AllArgsConstructor
    public static class ExecutionTimelineDTO {
        private Integer stepOrder;
        private String stepName;
        private String status;
        private Long duration;
        private String details;
        private String screenshotPath;
        private LocalDateTime timestamp;
    }
}
