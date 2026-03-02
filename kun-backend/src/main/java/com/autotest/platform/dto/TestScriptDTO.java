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
public class TestScriptDTO {
    
    private Long id;
    private String name;
    private ScriptType scriptType;
    private Language language;
    private String code;
    private String config;
    private Status status;
    private TestCaseDTO testCase;
    private String version;
    private String filePath;
    private LocalDateTime createdAt;
    private LocalDateTime updatedAt;
    
    public enum ScriptType {
        PLAYWRIGHT, SELENIUM, CYPRESS, APPIUM, REST_ASSURED
    }
    
    public enum Language {
        JAVASCRIPT, TYPESCRIPT, PYTHON, JAVA, CSHARP
    }
    
    public enum Status {
        DRAFT, GENERATING, READY, TESTING, PRODUCTION, DEPRECATED
    }
    
    @Data
    @Builder
    @NoArgsConstructor
    @AllArgsConstructor
    public static class CreateRequest {
        private String name;
        private ScriptType scriptType;
        private Language language;
        private String code;
        private String config;
        private Long testCaseId;
    }
    
    @Data
    @Builder
    @NoArgsConstructor
    @AllArgsConstructor
    public static class UpdateRequest {
        private String name;
        private String code;
        private String config;
        private Status status;
    }
    
    @Data
    @Builder
    @NoArgsConstructor
    @AllArgsConstructor
    public static class AIGenerateRequest {
        private Long testCaseId;
        private ScriptType scriptType;
        private Language language;
        private String targetUrl;
        private String additionalInstructions;
        private String feedback;
    }
    
    @Data
    @Builder
    @NoArgsConstructor
    @AllArgsConstructor
    public static class AIGenerateResponse {
        private String generatedCode;
        private String explanation;
        private String[] dependencies;
        private Long scriptId;
        private String recordId;
        private Integer version;
        private String runCommand;
        private String modelProvider;
        private String modelName;
    }

    @Data
    @Builder
    @NoArgsConstructor
    @AllArgsConstructor
    public static class ScriptGenerationEventDTO {
        private LocalDateTime occurredAt;
        private String stage;
        private String message;
    }

    @Data
    @Builder
    @NoArgsConstructor
    @AllArgsConstructor
    public static class ScriptGenerationMessageDTO {
        private String role;
        private String content;
        private LocalDateTime createdAt;
    }

    @Data
    @Builder
    @NoArgsConstructor
    @AllArgsConstructor
    public static class ScriptGenerationRecordDTO {
        private String recordId;
        private Integer version;
        private String sessionId;
        private String summary;
        private String feedback;
        private LocalDateTime generatedAt;
        private ScriptType scriptType;
        private Language language;
        private String targetUrl;
        private Long scriptId;
        private String scriptName;
        private String generatedCode;
        private List<String> dependencies;
        private String runCommand;
        private String modelProvider;
        private String modelName;
        private Boolean adopted;
        private LocalDateTime adoptedAt;
        private String adoptedBy;
    }

    @Data
    @Builder
    @NoArgsConstructor
    @AllArgsConstructor
    public static class ScriptGenerationSessionDTO {
        private Long testCaseId;
        private String caseNumber;
        private String sessionId;
        private Integer version;
        private String summary;
        private LocalDateTime updatedAt;
        private ScriptGenerationRecordDTO latestRecord;
        private List<ScriptGenerationMessageDTO> conversation;
    }
}
