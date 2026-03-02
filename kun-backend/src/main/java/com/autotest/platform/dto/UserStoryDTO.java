package com.autotest.platform.dto;

import com.autotest.platform.entity.UserStory;
import com.autotest.platform.entity.ValidationPoint;
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
public class UserStoryDTO {
    
    private Long id;
    private String usNumber;
    private String title;
    private String description;
    private String acceptanceCriteria;
    private UserStory.Priority priority;
    private UserStory.Status status;
    private String sprint;
    private String epic;
    private String storyPoints;
    private Long tenantId;
    private String tenantCode;
    private String tenantName;
    private String projectName;
    private UserDTO createdBy;
    private Integer testCaseCount;
    private Integer validationPointCount;
    private List<ValidationPointItemDTO> validationPoints;
    private LocalDateTime createdAt;
    private LocalDateTime updatedAt;

    @Data
    @Builder
    @NoArgsConstructor
    @AllArgsConstructor
    public static class ValidationPointItemDTO {
        private Long id;
        private String description;
        private String expectedResult;
        private ValidationPoint.Priority priority;
        private ValidationPoint.Status status;
    }
    
    @Data
    @Builder
    @NoArgsConstructor
    @AllArgsConstructor
    public static class CreateRequest {
        private String usNumber;
        private String title;
        private String description;
        private String acceptanceCriteria;
        private UserStory.Priority priority;
        private String sprint;
        private String epic;
        private String storyPoints;
    }
    
    @Data
    @Builder
    @NoArgsConstructor
    @AllArgsConstructor
    public static class UpdateRequest {
        private String title;
        private String description;
        private String acceptanceCriteria;
        private UserStory.Priority priority;
        private UserStory.Status status;
        private String sprint;
        private String epic;
        private String storyPoints;
    }
    
    @Data
    @Builder
    @NoArgsConstructor
    @AllArgsConstructor
    public static class AIAnalysisRequest {
        private String description;
        private String acceptanceCriteria;
    }
    
    @Data
    @Builder
    @NoArgsConstructor
    @AllArgsConstructor
    public static class AIAnalysisResponse {
        private Integer qualityScore;
        private List<QualityIssueDTO> qualityIssues;
        private String optimizedTitle;
        private String optimizedDescription;
        private String optimizedAcceptanceCriteria;
        private List<ValidationPointDTO> validationPoints;
        private List<TestCaseSuggestionDTO> suggestedTestCases;
        private String analysisSummary;
    }

    @Data
    @Builder
    @NoArgsConstructor
    @AllArgsConstructor
    public static class QualityIssueDTO {
        private String type;
        private String severity;
        private String message;
        private String suggestion;
    }
    
    @Data
    @Builder
    @NoArgsConstructor
    @AllArgsConstructor
    public static class ValidationPointDTO {
        private String description;
        private String expectedResult;
        private UserStory.Priority priority;
    }
    
    @Data
    @Builder
    @NoArgsConstructor
    @AllArgsConstructor
    public static class TestCaseSuggestionDTO {
        private String title;
        private String description;
        private TestCaseDTO.TestType testType;
        private TestCaseDTO.Priority priority;
    }

    @Data
    @Builder
    @NoArgsConstructor
    @AllArgsConstructor
    public static class GeneratedTestCaseDraftDTO {
        private String draftId;
        private String title;
        private String description;
        private String preconditions;
        private TestCaseDTO.TestType testType;
        private TestCaseDTO.Priority priority;
        private List<TestCaseDTO.TestStepDTO> steps;
        private String tags;
    }

    @Data
    @Builder
    @NoArgsConstructor
    @AllArgsConstructor
    public static class CaseGenerationMessageDTO {
        private String role;
        private String content;
        private LocalDateTime createdAt;
    }

    @Data
    @Builder
    @NoArgsConstructor
    @AllArgsConstructor
    public static class CaseGenerationEventDTO {
        private LocalDateTime occurredAt;
        private String stage;
        private String message;
    }

    @Data
    @Builder
    @NoArgsConstructor
    @AllArgsConstructor
    public static class CaseGenerationRecordDTO {
        private String recordId;
        private Integer version;
        private String summary;
        private String feedback;
        private LocalDateTime generatedAt;
        private List<CaseGenerationMessageDTO> conversation;
        private List<GeneratedTestCaseDraftDTO> draftCases;
    }

    @Data
    @Builder(toBuilder = true)
    @NoArgsConstructor
    @AllArgsConstructor
    public static class CaseGenerationSessionDTO {
        private String sessionId;
        private Integer version;
        private String summary;
        private LocalDateTime updatedAt;
        private List<CaseGenerationMessageDTO> conversation;
        private List<GeneratedTestCaseDraftDTO> draftCases;
        private List<String> adoptedDraftIds;
        private List<CaseGenerationRecordDTO> generationRecords;
    }
}
