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
public class TestCaseDTO {
    
    private Long id;
    private String caseNumber;
    private String title;
    private String description;
    private String preconditions;
    private TestType testType;
    private Priority priority;
    private Status status;
    private UserStoryDTO userStory;
    private UserDTO createdBy;
    private List<TestStepDTO> steps;
    private Boolean hasScript;
    private Integer executionCount;
    private String tags;
    private LocalDateTime createdAt;
    private LocalDateTime updatedAt;
    
    public enum TestType {
        FUNCTIONAL, UI, API, PERFORMANCE, SECURITY, COMPATIBILITY
    }
    
    public enum Priority {
        LOW, MEDIUM, HIGH, CRITICAL
    }
    
    public enum Status {
        DRAFT, REVIEW, READY, DEPRECATED, ARCHIVED
    }
    
    @Data
    @Builder
    @NoArgsConstructor
    @AllArgsConstructor
    public static class CreateRequest {
        private String title;
        private String description;
        private String preconditions;
        private TestType testType;
        private Priority priority;
        private Long userStoryId;
        private Long validationPointId;
        private List<TestStepDTO> steps;
        private String tags;
    }
    
    @Data
    @Builder
    @NoArgsConstructor
    @AllArgsConstructor
    public static class UpdateRequest {
        private String title;
        private String description;
        private String preconditions;
        private TestType testType;
        private Priority priority;
        private Status status;
        private List<TestStepDTO> steps;
        private String tags;
    }
    
    @Data
    @Builder
    @NoArgsConstructor
    @AllArgsConstructor
    public static class TestStepDTO {
        private Integer stepOrder;
        private String action;
        private String expectedResult;
        private String testData;
    }
}
